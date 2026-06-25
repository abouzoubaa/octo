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

    # unique askers: distinct pseudonyms among comments (searches + external signals
    # are anonymous, so they can't be deduped — counted as raw volume).
    pseudonyms = {c.author_pseudonym for c in comments if c.author_pseudonym}
    n_searches = sum(1 for s in cluster if s[0] == "search")
    n_external = sum(1 for s in cluster if str(s[0]).startswith("external:"))
    unique_askers = len(pseudonyms) + n_searches + n_external  # upper bound; comments deduped

    # organic vs CTA-prompted (searches + external signals are organic by nature)
    prompted = sum(1 for c in comments if _looks_prompted(c.text))
    organic = (len(comments) - prompted) + n_searches + n_external

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

    # --- manipulation risk: how inflatable is this demand signal? ---
    n_comments = len(comments)
    # duplicate near-identical comments (bot/copy farming)
    normalized = [" ".join(c.text.lower().split()) for c in comments if c.text]
    duplication_rate = (1.0 - len(set(normalized)) / len(normalized)) if normalized else 0.0
    # author concentration: a few people producing many comments
    concentration = (1.0 - len(pseudonyms) / n_comments) if n_comments else 0.0
    prompted_share = (prompted / n_comments) if n_comments else 0.0
    manipulation_risk = round(min(
        0.4 * prompted_share + 0.3 * duplication_rate + 0.3 * concentration, 1.0), 3)

    # --- exposure-normalized organic demand (asks per 1k impressions) ---
    demand_per_1k = _exposure_normalized(session, organic, cluster)

    # --- per-platform/source breakdown + segment label ---
    breakdown, segment = _demand_segmentation(session, comments, n_searches, cluster)

    return {
        "unique_askers": unique_askers,
        "organic_count": organic,
        "prompted_count": prompted,
        "persistence_weeks": prior_weeks + 1,
        "dominant_sentiment": dominant_sentiment,
        "intent_class": intent_class,
        "manipulation_risk": manipulation_risk,
        "duplication_rate": round(duplication_rate, 3),
        "demand_per_1k_impressions": demand_per_1k,
        "source_breakdown": breakdown,
        "demand_segment": segment,
    }


def _demand_segmentation(session: Session, comments: list, n_searches: int,
                         cluster: list[tuple] | None = None) -> tuple[dict, str]:
    """Where did this demand come from? Per-platform comment counts + on-site search
    + external sources (newsletter/podcast/forwarded).

    Segments: 'everywhere' (≥2 platforms/sources), 'platform:<x>' (one dominates),
    'search_only'. The same person is never merged across platforms — we count topics
    by source, not identities.
    """
    from cci_core.models import Post

    breakdown: dict[str, int] = {}
    if n_searches:
        breakdown["search"] = n_searches
    if comments:
        post_ids = [c.post_id for c in comments if c.post_id]
        plat_by_post = {}
        if post_ids:
            plat_by_post = {pid: plat for pid, plat in session.execute(
                select(Post.id, Post.platform).where(Post.id.in_(post_ids)))}
        for c in comments:
            plat = plat_by_post.get(c.post_id, "unknown") if c.post_id else "unknown"
            breakdown[plat] = breakdown.get(plat, 0) + 1
    # external sources from the cluster (kind 'external:<platform>')
    for s in (cluster or []):
        if str(s[0]).startswith("external:"):
            plat = str(s[0]).split(":", 1)[1] or "external"
            breakdown[plat] = breakdown.get(plat, 0) + 1
    platforms = [k for k in breakdown if k not in ("search", "unknown")]
    if len(platforms) >= 2:
        segment = "everywhere"
    elif platforms:
        segment = f"platform:{platforms[0]}"
    else:
        segment = "search_only"
    return breakdown, segment


def _exposure_normalized(session: Session, organic: int, cluster: list[tuple]) -> float | None:
    """Organic asks per 1,000 impressions of the posts that drove them. Needs the
    IG insights API (Post.impressions); returns None when impression data is absent,
    so demand is never over- or under-credited by reach we can't see."""
    from cci_core.models import Comment, Post

    comment_ids = [s[2] for s in cluster if s[0] == "comment" and s[2]]
    if not comment_ids:
        return None
    post_ids = set(session.scalars(
        select(Comment.post_id).where(Comment.id.in_(comment_ids))))
    impressions = session.scalar(
        select(func.sum(Post.impressions)).where(
            Post.id.in_([p for p in post_ids if p]), Post.impressions.isnot(None)))
    if not impressions:
        return None
    return round(organic / impressions * 1000.0, 3)


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


def repromote_topic(session: Session, topic: DemandTopic) -> dict:
    """Close a demand loop by re-promoting content the creator has ALREADY made.

    The make-new path runs new→idea→drafting→published→loop_closed. Re-promotion is
    the other way to close: the answer already exists (the topic is well/partly
    covered), so resurfacing it to the asking audience satisfies the demand directly.
    Records an Outcome (creator_action='repromote') and counts toward closed loops.
    """
    from cci_core.agent_foundations import advance_outcome, record_outcome
    from cci_core.models import DemandState

    permalink = ((topic.coverage or {}).get("permalinks") or [None])[0]
    outcome = record_outcome(session, topic.creator_id, source="demand",
                             demand_topic_id=topic.id, question_text=topic.label)
    advance_outcome(session, outcome.id, stage="closed", creator_action="repromote",
                    result={"via": "repromote", "permalink": permalink})
    closed = False
    if topic.state not in (DemandState.loop_closed, DemandState.dismissed):
        topic.state = DemandState.loop_closed
        topic.state_updated_at = datetime.now(timezone.utc)
        topic.creator_marked = "made"
        session.flush()
        closed = True
    return {"outcome_id": outcome.id, "state": topic.state.value,
            "closed": closed, "permalink": permalink}


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
    # confidence is further discounted by manipulation risk — brands shouldn't pay
    # for inflatable demand
    confidence *= (1.0 - 0.5 * (topic.manipulation_risk or 0.0))
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
        "manipulation_risk": topic.manipulation_risk,
        "duplication_rate": topic.duplication_rate,
        "demand_per_1k_impressions": topic.demand_per_1k_impressions,
        "confidence": round(confidence, 3),
        "issued_for": "brand comparison — aggregate, pseudonymous, no audience identities",
    }
