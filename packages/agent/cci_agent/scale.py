"""Scale intelligence (v3): performance prediction, content calendar, pricing &
offer insights, revenue forecasting, education planning, thumbnail concepts.

These need history to be reliable — they degrade gracefully (and say so) when the
creator's corpus/event history is thin.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cci_core.models import Comment, ContentDraft, DemandState, DemandTopic, Event, Post
from cci_providers import get_llm


# ----------------------------------------------------------- performance prediction


def predict_performance(session: Session, creator_id: str, draft: ContentDraft) -> dict:
    """Score a draft against the structural patterns of the creator's existing posts.

    Without real engagement data we score *structural fit* (hook presence, length
    band, topic demand), and say so — the proposal flags this needs history.
    """
    posts = session.scalars(
        select(Post).where(Post.creator_id == creator_id, Post.caption.isnot(None))
    ).all()
    n = len(posts)
    if n < 5:
        return {"score": None, "confidence": "low",
                "note": "needs more posting history to predict reliably"}

    cap_lengths = sorted(len((p.caption or "")) for p in posts)
    median = cap_lengths[len(cap_lengths) // 2]
    draft_len = len(draft.script or "") + len(" ".join(draft.hooks or []))

    score = 50
    if draft.hooks:
        score += 20  # has a hook
    if 0.5 * median <= draft_len <= 1.5 * median:
        score += 20  # length in the creator's usual band
    # demand alignment: is the draft's topic high-demand?
    if draft.demand_topic_id:
        topic = session.get(DemandTopic, draft.demand_topic_id)
        if topic and (topic.search_count + topic.comment_count) >= 3:
            score += 10
    score = min(score, 100)
    return {"score": score, "confidence": "medium" if n >= 20 else "low",
            "factors": {"has_hook": bool(draft.hooks),
                        "length_in_band": 0.5 * median <= draft_len <= 1.5 * median,
                        "median_caption_len": median},
            "note": "structural score (no engagement data); calibrate once metrics flow"}


# --------------------------------------------------------------- content calendar


def content_calendar(session: Session, creator_id: str) -> dict:
    """Cadence-aware production queue: items from the demand pipeline, a posting
    window inferred from past cadence, and over-saturation flags."""
    posts = session.scalars(
        select(Post).where(Post.creator_id == creator_id, Post.posted_at.isnot(None))
        .order_by(Post.posted_at.desc()).limit(30)
    ).all()
    dates = [p.posted_at for p in posts if p.posted_at]
    cadence_days = None
    if len(dates) >= 2:
        gaps = [(dates[i] - dates[i + 1]).days for i in range(len(dates) - 1)]
        gaps = [g for g in gaps if g >= 0]
        cadence_days = round(sum(gaps) / len(gaps), 1) if gaps else None

    # queue = demand items in idea/drafting, highest demand first
    queue_topics = session.scalars(
        select(DemandTopic).where(
            DemandTopic.creator_id == creator_id,
            DemandTopic.state.in_([DemandState.idea, DemandState.drafting]))
        .order_by((DemandTopic.search_count + DemandTopic.comment_count).desc())
    ).all()

    # over-saturation: a topic posted about a lot recently
    recent_topic_words = Counter()
    for p in posts[:10]:
        for w in (p.caption or "").lower().split():
            if len(w) > 5:
                recent_topic_words[w] += 1
    saturated = [w for w, c in recent_topic_words.items() if c >= 4]

    now = datetime.now(timezone.utc)
    next_slot = (now + timedelta(days=cadence_days)).date().isoformat() if cadence_days else None
    return {
        "cadence_days": cadence_days,
        "next_suggested_slot": next_slot,
        "queue": [{"topic_id": t.id, "label": t.label, "state": t.state.value,
                   "demand": t.search_count + t.comment_count} for t in queue_topics[:10]],
        "saturated_terms": saturated,
        "reactive_window_hours": 48,  # window for reacting to emerging trends
    }


# --------------------------------------------------------- pricing & offer insights


def pricing_insights(session: Session, creator_id: str) -> dict:
    """Read pre-purchase questions and objections to surface price-sensitivity signals."""
    comments = session.scalars(
        select(Comment).where(Comment.creator_id == creator_id, Comment.is_question.is_(True))
    ).all()
    price_qs, objections, bundle = [], [], []
    for c in comments:
        low = c.text.lower()
        if any(w in low for w in ("price", "cost", "how much", "$", "expensive", "afford")):
            price_qs.append(c.text)
            if any(w in low for w in ("expensive", "too much", "can't afford", "cheaper")):
                objections.append(c.text)
        if any(w in low for w in ("bundle", "package", "together", "discount", "deal")):
            bundle.append(c.text)
    insight = None
    if price_qs:
        insight = "Audience asks about price before content — consider a payment plan or clear value framing."
    return {"price_questions": len(price_qs), "objections": objections[:5],
            "bundle_signals": len(bundle), "insight": insight,
            "examples": price_qs[:5]}


# ------------------------------------------------------------- revenue forecasting


def revenue_forecast(session: Session, creator_id: str, *, days: int = 30) -> dict:
    """Project simple income trajectory from affiliate-click history and demand —
    a directional forecast, flagged as such."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    clicks = session.scalar(
        select(func.count(Event.id)).where(
            Event.creator_id == creator_id, Event.kind == "affiliate_click",
            Event.ts >= since)) or 0
    prev_clicks = session.scalar(
        select(func.count(Event.id)).where(
            Event.creator_id == creator_id, Event.kind == "affiliate_click",
            Event.ts >= since - timedelta(days=days), Event.ts < since)) or 0
    trend = "flat"
    if prev_clicks and clicks > prev_clicks * 1.1:
        trend = "up"
    elif prev_clicks and clicks < prev_clicks * 0.9:
        trend = "down"
    # linear extrapolation: continue the observed period-over-period delta, floored at 0
    projected = max(clicks + (clicks - prev_clicks), 0) if prev_clicks else clicks
    return {"window_days": days, "affiliate_clicks": clicks, "prev_window": prev_clicks,
            "trend": trend, "projected_next_window": projected,
            "note": "directional only — needs conversion + revenue data to be precise"}


# --------------------------------------------------------------- education planning


def education_plan(session: Session, creator_id: str) -> dict:
    """Identify skill gaps from patterns and propose a development plan."""
    n_posts = session.scalar(
        select(func.count(Post.id)).where(Post.creator_id == creator_id)) or 0
    n_with_transcript = session.scalar(
        select(func.count(Post.id)).select_from(Post)
        .where(Post.creator_id == creator_id, Post.type == "reel")) or 0
    facts = [f"{n_posts} posts", f"{n_with_transcript} video posts"]
    try:
        plan = json.loads(get_llm().complete(
            "Propose a creator skill-development plan (1/3/5-year) from these facts. "
            "JSON: {\"one_year\": [\"...\"], \"three_year\": [\"...\"], \"five_year\": [\"...\"]}.",
            "\n".join(facts), json_output=True, max_tokens=400))
    except Exception:  # noqa: BLE001
        plan = {"one_year": [], "three_year": [], "five_year": []}
    plan["based_on"] = facts
    return plan


# -------------------------------------------------------------- thumbnail concepts


def thumbnail_concepts(session: Session, creator_id: str, draft_title: str) -> dict:
    """Generate thumbnail concepts (text/layout ideas) for a draft. For visual-first
    creators; concept-level only (no image generation in scope)."""
    try:
        data = json.loads(get_llm().complete(
            "Propose 3 thumbnail concepts for a short-form video. JSON: "
            "{\"concepts\": [{\"text_overlay\": \"...\", \"layout\": \"face|no-face\", "
            "\"why\": \"...\"}]}.",
            f"Video: {draft_title}", json_output=True, max_tokens=400))
    except Exception:  # noqa: BLE001
        data = {"concepts": []}
    return data
