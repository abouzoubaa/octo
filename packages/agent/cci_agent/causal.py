"""Causal layer (Wave F): measure what WORKED, not just what correlated.

A demand-inspired post might outperform because of format, timing, or distribution
— not because the signal was predictive. This module gives every recommendation an
immutable intervention spine, a matched-topic baseline, a confidence interval (not
a deterministic score), opportunity holdouts as controls, and a holdout-vs-acted
lift estimate. Staggered publication keeps interventions from confounding each other.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cci_core.models import ContentDraft, DemandTopic, Event, Intervention, Post

HOLDOUT_RATE = 0.15  # ~15% of opportunities are held out as controls


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_holdout(topic_id: str) -> bool:
    """Deterministic holdout assignment — stable per topic, ~HOLDOUT_RATE of them."""
    h = int(hashlib.sha256(topic_id.encode()).hexdigest(), 16) % 1000
    return h < HOLDOUT_RATE * 1000


def matched_baseline(session: Session, creator_id: str, topic: DemandTopic) -> dict:
    """Creator-level historical control: typical outcome for this creator's prior
    posts on similar topics. Directional until real engagement data flows."""
    words = {w for w in (topic.label or "").lower().split() if len(w) > 3}
    posts = session.scalars(
        select(Post).where(Post.creator_id == creator_id, Post.caption.isnot(None))).all()
    matched = [p for p in posts
               if words & {w for w in (p.caption or "").lower().split() if len(w) > 3}]
    # affiliate clicks per matched post from the event log (a real, if sparse, signal)
    click_total = session.scalar(
        select(func.count(Event.id)).where(
            Event.creator_id == creator_id, Event.kind == "affiliate_click")) or 0
    n_posts = session.scalar(
        select(func.count(Post.id)).where(Post.creator_id == creator_id)) or 0
    return {
        "matched_posts": len(matched),
        "creator_avg_clicks_per_post": round(click_total / n_posts, 3) if n_posts else 0.0,
        "note": "creator historical control; directional until engagement data flows",
    }


def performance_interval(session: Session, creator_id: str, draft: ContentDraft) -> dict:
    """Confidence interval, NOT a point 'performance prediction'. The band WIDENS
    with less history, so thin data reads as uncertain rather than falsely precise."""
    n = session.scalar(
        select(func.count(Post.id)).where(Post.creator_id == creator_id)) or 0
    # structural fit point estimate (0..100), same signals as scale.predict_performance
    point = 50.0
    if draft.hooks:
        point += 20.0
    if draft.demand_topic_id:
        topic = session.get(DemandTopic, draft.demand_topic_id)
        if topic and (topic.search_count + topic.comment_count) >= 3:
            point += 10.0
    point = min(point, 100.0)
    # half-width shrinks ~1/sqrt(n): little history → wide, uncertain band
    half = 40.0 if n < 5 else max(8.0, 40.0 / (n ** 0.5))
    return {
        "point": round(point, 1),
        "low": round(max(point - half, 0.0), 1),
        "high": round(min(point + half, 100.0), 1),
        "n_history": n,
        "note": "structural-fit interval; not a guarantee. Widens with less history.",
    }


def create_intervention(session: Session, topic: DemandTopic, *,
                        draft: ContentDraft | None = None) -> Intervention:
    """Open an immutable intervention for an opportunity. Some are holdout controls."""
    holdout = _is_holdout(topic.id)
    iv = Intervention(
        creator_id=topic.creator_id,
        demand_topic_id=topic.id,
        draft_id=draft.id if draft else None,
        is_holdout=holdout,
        status="holdout" if holdout else "open",
        baseline=matched_baseline(session, topic.creator_id, topic),
        predicted=(performance_interval(session, topic.creator_id, draft) if draft else None),
    )
    session.add(iv)
    session.flush()
    return iv


def record_publication(session: Session, intervention_id: str, post_id: str) -> Intervention | None:
    iv = session.get(Intervention, intervention_id)
    if iv is None or iv.is_holdout:
        return iv
    iv.published_post_id = post_id
    iv.status = "published"
    iv.published_at = _utcnow()
    session.flush()
    return iv


def record_outcome(session: Session, intervention_id: str, metrics: dict) -> Intervention | None:
    iv = session.get(Intervention, intervention_id)
    if iv is None:
        return None
    iv.outcome = {**(iv.outcome or {}), **metrics}
    iv.status = "measured"
    iv.measured_at = _utcnow()
    session.flush()
    return iv


def holdout_lift(session: Session, creator_id: str, metric: str = "clicks") -> dict:
    """Estimate lift: measured outcome of ACTED interventions vs HOLDOUT controls.

    The honest version of 'did Sift's recommendation cause the result?' — compares
    against opportunities we deliberately didn't act on, not just before/after.
    """
    rows = session.scalars(
        select(Intervention).where(Intervention.creator_id == creator_id,
                                   Intervention.outcome.isnot(None))).all()
    acted = [r.outcome.get(metric, 0) for r in rows if not r.is_holdout and r.outcome]
    held = [r.outcome.get(metric, 0) for r in rows if r.is_holdout and r.outcome]
    acted_avg = sum(acted) / len(acted) if acted else None
    held_avg = sum(held) / len(held) if held else None
    lift = None
    if acted_avg is not None and held_avg:
        lift = round((acted_avg - held_avg) / held_avg, 3)
    return {
        "metric": metric,
        "acted_n": len(acted), "acted_avg": acted_avg,
        "holdout_n": len(held), "holdout_avg": held_avg,
        "lift": lift,
        "note": ("not enough measured data for a confident lift estimate"
                 if lift is None else "lift vs deliberately-held-out controls"),
    }


def stagger_publications(draft_ids: list[str], *, cadence_days: float = 2.0,
                         start: datetime | None = None) -> list[dict]:
    """Space interventions out so they don't confound each other's measurement."""
    start = start or _utcnow()
    return [{"draft_id": did,
             "suggested_publish_at": (start + timedelta(days=cadence_days * i)).date().isoformat()}
            for i, did in enumerate(draft_ids)]
