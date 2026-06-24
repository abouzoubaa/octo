"""Growth & ecosystem (v3): peer benchmarking, competitor demand radar, plagiarism
monitoring, task/PM integration.

The opt-in features (benchmarking, competitor radar) stay OFF by default and only
ever operate on aggregate/anonymised data — never individual cross-creator matching.
Marketplace & brand portal are gated on multi-creator scale and intentionally left
as scaffolds until the single-creator loop is proven.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cci_core.agent_foundations import get_rules
from cci_core.models import DemandTopic, Post
from cci_providers import get_embedding_provider


# ----------------------------------------------------------------- peer benchmarking


def peer_benchmark(session: Session, creator_id: str) -> dict:
    """Contextualise the creator against aggregate peer norms — opt-in only.

    v3 ships the creator's own stats vs placeholder anonymised aggregates until a
    real multi-creator panel exists; the gate (opt-in) and shape are what matter now.
    """
    rules = get_rules(session, creator_id)
    if not rules.allow_benchmarking:
        return {"enabled": False, "note": "peer benchmarking is opt-in; not enabled"}

    n_posts = session.scalar(
        select(func.count(Post.id)).where(Post.creator_id == creator_id)) or 0
    n_topics = session.scalar(
        select(func.count(DemandTopic.id)).where(DemandTopic.creator_id == creator_id)) or 0
    # anonymised aggregate norms (placeholder until a real panel exists)
    norms = {"median_posts": 120, "median_active_topics": 15}
    return {
        "enabled": True,
        "you": {"posts": n_posts, "active_topics": n_topics},
        "peer_median": norms,
        "gaps": {
            "posts_vs_median": n_posts - norms["median_posts"],
            "topics_vs_median": n_topics - norms["median_active_topics"],
        },
        "note": "aggregate/anonymised; no individual peer identification",
    }


def competitor_radar(session: Session, creator_id: str) -> dict:
    """How a similar creator answered the same demand — opt-in, aggregate, topic-level.

    Scaffolded: returns the creator's own top demand topics framed for comparison;
    a real implementation joins an opted-in aggregate panel (never scraping)."""
    rules = get_rules(session, creator_id)
    if not rules.allow_competitor_radar:
        return {"enabled": False, "note": "competitor radar is opt-in; not enabled"}
    topics = session.scalars(
        select(DemandTopic).where(DemandTopic.creator_id == creator_id)
        .order_by((DemandTopic.search_count + DemandTopic.comment_count).desc()).limit(5)
    ).all()
    return {
        "enabled": True,
        "topics": [{"label": t.label, "your_coverage": (t.coverage or {}).get("strength", 0.0)}
                   for t in topics],
        "note": "topic-level aggregate only; never individual identity matching (GDPR)",
    }


# ----------------------------------------------------------------- plagiarism scan


def plagiarism_scan(session: Session, creator_id: str, external_text: str,
                    threshold: float = 0.82) -> dict:
    """Detect whether external text closely matches the creator's own content
    (a repost/scrape signal). Uses embedding similarity against the index."""
    if not external_text.strip():
        return {"match": False}
    vec = get_embedding_provider().embed_one(external_text)
    from sqlalchemy import text as sql_text

    rows = session.execute(
        sql_text(
            """
            SELECT c.post_id, 1 - (c.embedding <=> CAST(:qvec AS vector)) AS sim
            FROM chunks c
            WHERE c.creator_id = :cid AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> CAST(:qvec AS vector)
            LIMIT 1
            """
        ),
        {"qvec": str(vec), "cid": creator_id},
    ).fetchone()
    if rows is None:
        return {"match": False}
    post_id, sim = rows[0], float(rows[1])
    post = session.get(Post, post_id)
    return {
        "match": sim >= threshold,
        "similarity": round(sim, 3),
        "matched_post": post.permalink if post else None,
        "suggestion": "review for unauthorised reuse; offer takedown/outreach" if sim >= threshold else None,
    }


# ----------------------------------------------------------------- task / PM export


def export_task(session: Session, creator_id: str, topic: DemandTopic,
                provider: str = "fake") -> dict:
    """Turn a Radar card into a tracked task payload for Notion/Asana/Linear.

    Returns the normalised task; a real provider posts it via its API. The 'fake'
    provider just returns the payload (used in dev/tests), keeping this portable.
    """
    due = datetime.now(timezone.utc).date().isoformat()
    payload = {
        "title": f"Create: {topic.label}",
        "description": topic.recommendation or "",
        "due_date": due,
        "source": "sift-demand-radar",
        "demand_topic_id": topic.id,
        "provider": provider,
    }
    # real providers (notion/asana/linear) would POST here behind a thin interface;
    # default 'fake' returns the payload so the flow is testable offline.
    return {"exported": provider == "fake", "task": payload}
