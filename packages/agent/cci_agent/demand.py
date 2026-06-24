"""Demand intelligence: Demand Integrity + the explainable Opportunity Score.

ChatGPT's strongest technical critique: a raw event count is not trustworthy
demand. This module turns a cluster into integrity-aware signals (unique askers,
organic vs CTA-prompted, persistence, sentiment, intent) and a transparent
Opportunity Score whose components are exposed rather than a black box.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cci_core.models import Comment, DemandTopic, Post


def _looks_prompted(text: str) -> bool:
    """CTA-driven asks look different from spontaneous questions: a single keyword,
    an all-caps trigger ('PLAN'), or a very short token reply."""
    t = (text or "").strip()
    if not t:
        return False
    words = t.split()
    if len(words) <= 1:  # single token → almost always a CTA response
        return True
    if t.isupper() and len(t) <= 20:  # SHORT ALL-CAPS trigger
        return True
    return False


def compute_integrity(session: Session, creator_id: str, cluster: list[tuple],
                      label: str, week: str) -> dict:
    """Integrity signals for a demand cluster. `cluster` is [(kind, text, comment_id)]."""
    comment_ids = [s[2] for s in cluster if s[0] == "comment" and s[2]]
    comments = []
    if comment_ids:
        comments = list(session.scalars(
            select(Comment).where(Comment.id.in_(comment_ids))))

    # unique askers: distinct pseudonyms among comments (searches are anonymous, so
    # they can't be deduped — counted separately as raw search volume).
    pseudonyms = {c.author_pseudonym for c in comments if c.author_pseudonym}
    n_searches = sum(1 for s in cluster if s[0] == "search")
    unique_askers = len(pseudonyms) + n_searches  # upper bound; comments deduped

    # organic vs CTA-prompted
    prompted = sum(1 for c in comments if _looks_prompted(c.text))
    organic = (len(comments) - prompted) + n_searches  # searches are organic by nature

    # dominant sentiment across the cluster's question-comments
    sentiments = [c.sentiment for c in comments if c.sentiment and c.sentiment != "neutral"]
    dominant_sentiment = Counter(sentiments).most_common(1)[0][0] if sentiments else "neutral"

    # intent class from the representative question
    from cci_agent.inbox import label_message

    representative = max((s[1] for s in cluster), key=len) if cluster else label
    inbox_label = label_message(representative, use_llm=False)
    intent_class = {"purchase_intent": "purchase", "content_request": "learning",
                    "support": "support"}.get(inbox_label, "other")

    # persistence: how many distinct prior weeks a topic with this label appeared
    prior_weeks = session.scalar(
        select(func.count(func.distinct(DemandTopic.week))).where(
            DemandTopic.creator_id == creator_id,
            func.lower(DemandTopic.label) == label.lower(),
            DemandTopic.week != week)
    ) or 0

    return {
        "unique_askers": unique_askers,
        "organic_count": organic,
        "prompted_count": prompted,
        "persistence_weeks": prior_weeks + 1,
        "dominant_sentiment": dominant_sentiment,
        "intent_class": intent_class,
    }


# ------------------------------------------------------------- opportunity score

_WEIGHTS = {  # sum to 100 before penalties
    "demand_volume": 25, "velocity": 15, "persistence": 15,
    "coverage_gap": 20, "commercial_intent": 15, "unmet_need": 10,
}
_UNMET_SENTIMENTS = {"confusion", "frustration", "anxiety"}


def _topic_fatigue(session: Session, creator_id: str, coverage: dict | None) -> float:
    """Saturation: did the creator already post on this topic recently? Posting again
    into a fresh, well-covered topic is low-opportunity ('covered twice this month')."""
    post_ids = (coverage or {}).get("post_ids") or []
    if not post_ids:
        return 0.0
    since = datetime.now(timezone.utc) - timedelta(days=30)
    recent = session.scalar(
        select(func.count(Post.id)).where(
            Post.id.in_(post_ids), Post.posted_at.isnot(None), Post.posted_at >= since)
    ) or 0
    return min(recent / 3.0, 1.0)


def opportunity_score(session: Session, creator_id: str, *, volume: int,
                      velocity_pct: float | None, persistence_weeks: int,
                      coverage_strength: float, intent_class: str | None,
                      has_offer: bool, dominant_sentiment: str | None,
                      coverage: dict | None) -> dict:
    """Transparent 0–100 score with every component exposed (not a black box)."""
    components = {
        "demand_volume": round(min(volume / 20.0, 1.0), 3),  # 20+ signals → max
        "velocity": round(max(min((velocity_pct or 0.0) / 100.0, 1.0), 0.0), 3),  # +100% → max
        "persistence": round(min(persistence_weeks / 4.0, 1.0), 3),  # 4 weeks → max
        "coverage_gap": round(max(1.0 - coverage_strength, 0.0), 3),  # weak coverage = opportunity
        "commercial_intent": round(
            1.0 if intent_class == "purchase" else (0.6 if has_offer else 0.2), 3),
        "unmet_need": round(0.2 if dominant_sentiment in _UNMET_SENTIMENTS else 0.0, 3),
    }
    fatigue = _topic_fatigue(session, creator_id, coverage)
    raw = sum(components[k] * w for k, w in _WEIGHTS.items())  # 0..100
    score = max(0.0, raw - fatigue * 20.0)  # fatigue penalty up to -20
    components["fatigue_penalty"] = round(fatigue, 3)
    return {"score": round(min(score, 100.0), 1), "components": components}


def score_topic(session: Session, topic: DemandTopic) -> dict:
    """Score an already-built DemandTopic (used by the API / re-scoring)."""
    return opportunity_score(
        session, topic.creator_id,
        volume=topic.search_count + topic.comment_count,
        velocity_pct=topic.wow_change, persistence_weeks=topic.persistence_weeks,
        coverage_strength=(topic.coverage or {}).get("strength", 0.0),
        intent_class=topic.intent_class, has_offer=bool(topic.linked_products),
        dominant_sentiment=topic.dominant_sentiment, coverage=topic.coverage,
    )


# ------------------------------------------------------------- north-star metric


def closed_loops(session: Session, creator_id: str, *, weeks: int = 8) -> dict:
    """THE company metric: closed demand loops per active creator per week.

    A loop closes when a demand item reaches `loop_closed` (need detected → creator
    acted → content published → askers notified). Search volume and draft counts
    can be gamed; closed loops measure the actual promise of Sift.
    """
    from cci_core.models import DemandState

    since = datetime.now(timezone.utc) - timedelta(weeks=weeks)
    closed = session.scalar(
        select(func.count(DemandTopic.id)).where(
            DemandTopic.creator_id == creator_id,
            DemandTopic.state == DemandState.loop_closed,
            DemandTopic.state_updated_at >= since)
    ) or 0
    # acted-but-not-yet-closed (in-flight loops) for context
    in_flight = session.scalar(
        select(func.count(DemandTopic.id)).where(
            DemandTopic.creator_id == creator_id,
            DemandTopic.state.in_([DemandState.idea, DemandState.drafting,
                                   DemandState.published]))
    ) or 0
    return {
        "window_weeks": weeks,
        "closed_loops": closed,
        "closed_loops_per_week": round(closed / weeks, 2),
        "in_flight_loops": in_flight,
    }


# ------------------------------------------------------------- demand certificate


def demand_certificate(session: Session, topic: DemandTopic) -> dict:
    """A privacy-preserving certificate of demand for a topic — the standard unit a
    brand could compare, WITHOUT seeing raw audience identities or quotes.

    Carries integrity metrics + the opportunity components + a confidence band that
    widens with thin/CTA-prompted data. No verbatims, no pseudonyms, no PII.
    """
    total = topic.search_count + topic.comment_count
    prompted_share = (topic.prompted_count / total) if total else 0.0
    # confidence falls with low volume, short persistence, and high prompted share
    confidence = (
        min(topic.unique_askers / 20.0, 1.0) * 0.4
        + min(topic.persistence_weeks / 4.0, 1.0) * 0.3
        + (1.0 - prompted_share) * 0.3
    )
    return {
        "topic": topic.label,
        "week": topic.week,
        "unique_askers": topic.unique_askers,
        "total_signals": total,
        "organic_share": round(1.0 - prompted_share, 3),
        "persistence_weeks": topic.persistence_weeks,
        "velocity_wow_pct": topic.wow_change,
        "intent_class": topic.intent_class,
        "dominant_sentiment": topic.dominant_sentiment,
        "coverage_gap": bool((topic.coverage or {}).get("gap")),
        "opportunity_score": topic.opportunity_score,
        "confidence": round(confidence, 3),
        "issued_for": "brand comparison — aggregate, pseudonymous, no audience identities",
    }
