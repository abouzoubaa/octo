"""Demand Radar — cluster questions into decision-ready evidence cards (plan §4.6).

Cold start: runs over the historical comment backlog, so the creator sees value
before the audience ever searches. Weekly: clusters the week's searches +
question-comments, compares week-over-week, checks coverage against the corpus.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.db import session_scope
from cci_core.models import Comment, DemandTopic, Product, Query
from cci_providers import get_embedding_provider, get_llm
from cci_retrieval.search import retrieval_confidence, search

log = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.72  # cosine sim to join an existing cluster
MIN_CLUSTER_SIZE = 2  # singleton questions are noise at weekly granularity
CARD_SYSTEM = """\
You turn a cluster of real audience questions into one Demand Radar evidence card
for a creator. Given the questions and the creator's current coverage, return JSON:
{"label": "short topic name",
 "recommendation": "one concrete post idea, e.g. Reel: '3 no-egg high-protein breakfasts under 10 minutes'",
 "confidence": "high"|"medium"|"low"}
Ground the recommendation in the audience's actual phrasing.\
"""


def _iso_week(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def build_radar(creator_id: str, *, backlog: bool = False) -> int:
    """Cluster demand signals into evidence cards. `backlog=True` = cold-start mode
    over all history; otherwise the trailing 7 days."""
    now = datetime.now(timezone.utc)
    since = None if backlog else now - timedelta(days=7)
    week = _iso_week(now)

    with session_scope() as session:
        texts = _collect_signals(session, creator_id, since)
        if not texts:
            return 0
        clusters = _cluster(texts)
        prev_counts = _previous_week_counts(session, creator_id, now)

        cards = 0
        for cluster in clusters:
            if len(cluster) < MIN_CLUSTER_SIZE and not backlog:
                continue
            card = _make_card(session, creator_id, cluster, week, prev_counts)
            if card is not None:
                session.add(card)
                cards += 1
        return cards


def _collect_signals(session: Session, creator_id: str,
                     since: datetime | None) -> list[tuple[str, str]]:
    """Return (kind, text) where kind ∈ {search, comment}."""
    q_stmt = select(Query.text).where(Query.creator_id == creator_id)
    c_stmt = select(Comment.text).where(
        Comment.creator_id == creator_id, Comment.is_question.is_(True)
    )
    if since is not None:
        q_stmt = q_stmt.where(Query.created_at >= since)
        c_stmt = c_stmt.where(Comment.ingested_at >= since)
    signals = [("search", t) for t in session.scalars(q_stmt)]
    signals += [("comment", t) for t in session.scalars(c_stmt)]
    return [(k, t.strip()) for k, t in signals if t and t.strip()]


def _cluster(signals: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Greedy centroid clustering over embeddings — simple, deterministic, plenty for v1."""
    texts = [t for _, t in signals]
    vectors = np.array(get_embedding_provider().embed(texts), dtype=float)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors = vectors / norms

    centroids: list[np.ndarray] = []
    clusters: list[list[tuple[str, str]]] = []
    for signal, vec in zip(signals, vectors):
        best_i, best_sim = -1, 0.0
        for i, centroid in enumerate(centroids):
            sim = float(vec @ centroid)
            if sim > best_sim:
                best_i, best_sim = i, sim
        if best_i >= 0 and best_sim >= SIMILARITY_THRESHOLD:
            clusters[best_i].append(signal)
            n = len(clusters[best_i])
            centroids[best_i] = (centroids[best_i] * (n - 1) + vec) / n
            centroids[best_i] /= np.linalg.norm(centroids[best_i]) or 1.0
        else:
            centroids.append(vec)
            clusters.append([signal])
    clusters.sort(key=len, reverse=True)
    return clusters


def _previous_week_counts(session: Session, creator_id: str, now: datetime) -> dict[str, int]:
    prev_week = _iso_week(now - timedelta(days=7))
    rows = session.scalars(
        select(DemandTopic).where(
            DemandTopic.creator_id == creator_id, DemandTopic.week == prev_week
        )
    ).all()
    return {t.label.lower(): t.search_count + t.comment_count for t in rows}


def _make_card(session: Session, creator_id: str, cluster: list[tuple[str, str]],
               week: str, prev_counts: dict[str, int]) -> DemandTopic | None:
    search_count = sum(1 for k, _ in cluster if k == "search")
    comment_count = sum(1 for k, _ in cluster if k == "comment")
    verbatims = [t for _, t in cluster][:5]

    # coverage check: does the corpus already answer this?
    representative = max((t for _, t in cluster), key=len)
    results = search(session, creator_id, representative, top_k=3)
    confidence = retrieval_confidence(results)
    coverage = {
        "post_ids": [r.post_id for r in results],
        "permalinks": [r.permalink for r in results if r.permalink],
        "strength": round(confidence, 3),
        "gap": confidence < 0.5,
    }

    try:
        data = json.loads(get_llm().complete(
            CARD_SYSTEM,
            "Questions:\n" + "\n".join(f"- {v}" for v in verbatims)
            + f"\n\nExisting coverage strength: {confidence:.2f} "
            + ("(weak — content gap)" if coverage["gap"] else "(already covered)"),
            json_output=True, max_tokens=300,
        ))
    except Exception as exc:  # noqa: BLE001
        log.warning("radar card LLM failed: %s", exc)
        data = {"label": verbatims[0][:80], "recommendation": None, "confidence": "low"}

    label = (data.get("label") or verbatims[0][:80]).strip()
    total = search_count + comment_count
    prev = prev_counts.get(label.lower())
    wow = ((total - prev) / prev * 100.0) if prev else None

    # linked products: approved products whose name appears in the audience language
    products = session.scalars(
        select(Product).where(Product.creator_id == creator_id, Product.approved.is_(True))
    ).all()
    blob = " ".join(verbatims).lower()
    linked = [{"id": p.id, "name": p.name} for p in products if p.name.lower() in blob]

    return DemandTopic(
        creator_id=creator_id,
        label=label,
        week=week,
        search_count=search_count,
        comment_count=comment_count,
        wow_change=wow,
        coverage=coverage,
        audience_language=verbatims,
        recommendation=data.get("recommendation"),
        linked_products=linked or None,
        confidence=data.get("confidence", "medium"),
    )
