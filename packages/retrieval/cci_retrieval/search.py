"""Hybrid retrieval: Postgres full-text + pgvector cosine → merged → reranked.

One retrieval layer powers the search bar, the answer card, and comment-to-DM
(plan §4.4). Results are post-level with chunk evidence and a confidence score.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from cci_core.config import get_settings
from cci_providers import get_embedding_provider

RRF_K = 60  # reciprocal-rank-fusion constant


@dataclass
class ChunkHit:
    chunk_id: str
    post_id: str
    source: str
    text: str
    start_ts: float | None
    score: float


@dataclass
class PostResult:
    post_id: str
    permalink: str | None
    caption: str | None
    post_type: str
    posted_at: str | None
    score: float
    evidence: list[ChunkHit] = field(default_factory=list)
    # confidence inputs: best raw cosine similarity + lexical agreement
    vec_sim: float = 0.0
    fts_support: bool = False


def _vector_candidates(session: Session, creator_id: str, query_vec: list[float],
                       limit: int) -> list[ChunkHit]:
    rows = session.execute(
        sql_text(
            """
            SELECT c.id, c.post_id, c.source, c.text, c.start_ts,
                   1 - (c.embedding <=> CAST(:qvec AS vector)) AS sim
            FROM chunks c
            JOIN posts p ON p.id = c.post_id AND p.status = 'active'
            WHERE c.creator_id = :creator_id AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> CAST(:qvec AS vector)
            LIMIT :limit
            """
        ),
        {"qvec": str(query_vec), "creator_id": creator_id, "limit": limit},
    ).fetchall()
    return [ChunkHit(r[0], r[1], r[2], r[3], r[4], float(r[5])) for r in rows]


def _fulltext_candidates(session: Session, creator_id: str, query: str,
                         limit: int) -> list[ChunkHit]:
    rows = session.execute(
        sql_text(
            """
            SELECT c.id, c.post_id, c.source, c.text, c.start_ts,
                   ts_rank(c.tsv, websearch_to_tsquery('english', :q)) AS rank
            FROM chunks c
            JOIN posts p ON p.id = c.post_id AND p.status = 'active'
            WHERE c.creator_id = :creator_id
              AND c.tsv @@ websearch_to_tsquery('english', :q)
            ORDER BY rank DESC
            LIMIT :limit
            """
        ),
        {"q": query, "creator_id": creator_id, "limit": limit},
    ).fetchall()
    return [ChunkHit(r[0], r[1], r[2], r[3], r[4], float(r[5])) for r in rows]


def _rrf_merge(*ranked_lists: list[ChunkHit]) -> list[ChunkHit]:
    """Reciprocal-rank fusion across retrievers; robust without score calibration."""
    fused: dict[str, ChunkHit] = {}
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            fused.setdefault(hit.chunk_id, hit)
    merged = []
    for cid, hit in fused.items():
        merged.append(ChunkHit(hit.chunk_id, hit.post_id, hit.source, hit.text,
                               hit.start_ts, scores[cid]))
    merged.sort(key=lambda h: h.score, reverse=True)
    return merged


def _rerank(query: str, merged: list[ChunkHit]) -> list[ChunkHit]:
    """Reorder merged candidates with the configured reranker (no-op if 'none').

    The reranker reorders the top candidates; we blend its 0..1 relevance into the
    RRF score so the post-grouping below still has a meaningful magnitude. Tail
    candidates beyond rerank_candidates keep their fused order.
    """
    from cci_providers import get_reranker

    reranker = get_reranker()
    if reranker is None or not merged:
        return merged
    from cci_core.config import get_settings

    head = merged[: get_settings().rerank_candidates]
    tail = merged[get_settings().rerank_candidates :]
    scores = reranker.rerank(query, [h.text for h in head])
    rescored = []
    for hit, rel in zip(head, scores):
        # keep RRF as a tie-breaker; relevance dominates ordering
        blended = rel + 1e-3 * hit.score
        rescored.append(ChunkHit(hit.chunk_id, hit.post_id, hit.source, hit.text,
                                 hit.start_ts, blended))
    rescored.sort(key=lambda h: h.score, reverse=True)
    return rescored + tail


def search(session: Session, creator_id: str, query: str,
           top_k: int | None = None) -> list[PostResult]:
    """Hybrid search returning post-level results with chunk evidence."""
    s = get_settings()
    top_k = top_k or s.search_top_k
    n_candidates = s.rerank_candidates

    query_vec = get_embedding_provider().embed_one(query)
    vec_hits = _vector_candidates(session, creator_id, query_vec, n_candidates)
    fts_hits = _fulltext_candidates(session, creator_id, query, n_candidates)
    merged = _rrf_merge(vec_hits, fts_hits)
    merged = _rerank(query, merged)  # second-pass relevance model (no-op if disabled)

    vec_sim_by_post: dict[str, float] = {}
    for hit in vec_hits:
        vec_sim_by_post[hit.post_id] = max(vec_sim_by_post.get(hit.post_id, 0.0), hit.score)
    fts_posts = {hit.post_id for hit in fts_hits}

    # group chunk hits by post; post score = max chunk score with a small
    # bonus per extra supporting chunk (multiple matches = stronger signal)
    by_post: dict[str, list[ChunkHit]] = {}
    for hit in merged:
        by_post.setdefault(hit.post_id, []).append(hit)

    post_ids = list(by_post.keys())
    if not post_ids:
        return []
    rows = session.execute(
        sql_text(
            "SELECT id, permalink, caption, type, posted_at FROM posts "
            "WHERE id = ANY(:ids) AND status = 'active'"
        ),
        {"ids": post_ids},
    ).fetchall()
    posts_meta = {r[0]: r for r in rows}

    results: list[PostResult] = []
    for post_id, hits in by_post.items():
        meta = posts_meta.get(post_id)
        if meta is None:
            continue
        score = max(h.score for h in hits) * (1 + 0.1 * (len(hits) - 1))
        results.append(
            PostResult(
                post_id=post_id,
                permalink=meta[1],
                caption=meta[2],
                post_type=meta[3],
                posted_at=meta[4].isoformat() if meta[4] else None,
                score=score,
                evidence=sorted(hits, key=lambda h: h.score, reverse=True)[:3],
                vec_sim=vec_sim_by_post.get(post_id, 0.0),
                fts_support=post_id in fts_posts,
            )
        )
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]


def retrieval_confidence(results: list[PostResult]) -> float:
    """Confidence in the top result, based on absolute signal — not rank.

    Rank alone can't distinguish "best of nothing" from a real hit, so we blend
    the best raw cosine similarity with lexical agreement (the top post was also
    found by full-text search). The eval harness calibrates the thresholds.
    """
    if not results:
        return 0.0
    top = results[0]
    return min(0.6 * max(top.vec_sim, 0.0) + 0.4 * (1.0 if top.fts_support else 0.0), 1.0)
