"""The Briefing (v1.5) + content gap map.

The Briefing is a pushed digest, not a dashboard nobody visits: top demand
signals with ready hooks, a re-promotion pick (already answered well), open gaps,
and one fully drafted post. The content gap map classifies the archive's coverage.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.deep_links import search_link
from cci_core.models import Creator, DemandTopic
from cci_retrieval.search import search

TOP_N = 5


def _iso_week(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def content_gap_map(session: Session, creator_id: str, week: str | None = None) -> list[dict]:
    """Classify each demand topic's coverage: well | partial | gap.

    Goes beyond "what's common" to a strategic map of what the archive answers.
    """
    stmt = select(DemandTopic).where(DemandTopic.creator_id == creator_id)
    if week:
        stmt = stmt.where(DemandTopic.week == week)
    out = []
    for topic in session.scalars(stmt):
        strength = (topic.coverage or {}).get("strength", 0.0)
        if strength >= 0.6:
            coverage = "well"
        elif strength >= 0.35:
            coverage = "partial"
        else:
            coverage = "gap"
        out.append({
            "topic_id": topic.id, "label": topic.label, "coverage": coverage,
            "strength": strength, "demand": topic.search_count + topic.comment_count,
            "state": topic.state.value,
        })
    out.sort(key=lambda d: (d["coverage"] != "gap", -d["demand"]))
    return out


def build_briefing(session: Session, creator_id: str, *, with_draft: bool = True) -> dict | None:
    """Assemble the pushed Briefing for the current week."""
    creator = session.get(Creator, creator_id)
    if creator is None:
        return None
    week = _iso_week(datetime.now(timezone.utc))

    cards = session.scalars(
        select(DemandTopic)
        .where(DemandTopic.creator_id == creator_id, DemandTopic.week == week)
        .order_by((DemandTopic.search_count + DemandTopic.comment_count).desc())
        .limit(TOP_N)
    ).all()
    if not cards:
        return None

    gap_map = content_gap_map(session, creator_id, week)
    gaps = [g for g in gap_map if g["coverage"] == "gap"]
    well = [g for g in gap_map if g["coverage"] == "well"]

    # re-promotion pick: a well-covered, high-demand topic worth resurfacing
    repromote = None
    if well:
        best = max(well, key=lambda g: g["demand"])
        res = search(session, creator_id, best["label"], top_k=1)
        if res:
            repromote = {"label": best["label"], "permalink": res[0].permalink,
                         "why": "you already answered this well — resurface it"}

    briefing = {
        "week": week,
        "creator": creator.handle,
        "top_demand": [{
            "topic_id": c.id, "label": c.label,
            "signal": {"searches": c.search_count, "comments": c.comment_count,
                       "wow_change": c.wow_change},
            "hook": (c.audience_language[0] if c.audience_language else None),
            "state": c.state.value,
        } for c in cards],
        "open_gaps": [{"label": g["label"], "demand": g["demand"]} for g in gaps[:3]],
        "repromote": repromote,
        "archive_link": search_link(creator.handle),
    }

    # originality mix: don't trap the creator in a purely reactive local maximum.
    # Surface one ADJACENT exploration (a topic they cover that isn't in this week's
    # demand) and one CONVICTION prompt (post what you care about, not just what's asked).
    briefing["originality"] = _originality_mix(session, creator_id, cards)

    if with_draft and cards:
        # one fully-drafted post for the single highest-signal gap (or top card)
        target = next((c for c in cards
                       if any(g["topic_id"] == c.id and g["coverage"] == "gap" for g in gap_map)),
                      cards[0])
        from cci_agent.drafting import generate_draft

        draft = generate_draft(session, creator_id, target, persist=True)
        briefing["drafted_post"] = {
            "draft_id": draft.id, "title": draft.title,
            "hooks": draft.hooks, "script": draft.script, "cta": draft.cta,
        }
    return briefing


def _originality_mix(session: Session, creator_id: str, cards: list) -> dict:
    """An adjacent exploration + a conviction prompt — to preserve creator taste."""
    from collections import Counter

    from cci_core.models import Enrichment, Post

    demand_labels = {(c.label or "").lower() for c in cards}
    # adjacent: a topic the creator covers that the audience ISN'T currently asking about
    rows = session.execute(
        select(Enrichment.topics).join(Post, Post.id == Enrichment.post_id)
        .where(Post.creator_id == creator_id, Post.status == "active")).all()
    counts: Counter = Counter()
    for (topics,) in rows:
        for t in (topics or []):
            counts[str(t).strip().lower()] += 1
    adjacent = next((t for t, _ in counts.most_common()
                     if t and not any(t in d or d in t for d in demand_labels)), None)
    return {
        "adjacent_exploration": (
            {"topic": adjacent, "why": "you cover this but the audience isn't asking — "
             "a chance to lead rather than react"} if adjacent else None),
        "conviction_prompt": "Post one thing this week because YOU believe it matters — "
                             "not because it was requested. Sift optimises the business; "
                             "your taste is the product.",
    }


def render_briefing_text(briefing: dict) -> str:
    """Plain-text Briefing for email/DM delivery (the digest comes to the creator)."""
    lines = [
        f"📡 Your Sift Briefing — week {briefing['week']}, @{briefing['creator']}",
        "What your audience wants and what to do about it:",
        "",
    ]
    for i, d in enumerate(briefing["top_demand"], 1):
        sig = d["signal"]
        wow = f", {sig['wow_change']:+.0f}% WoW" if sig.get("wow_change") is not None else ""
        lines.append(f"{i}. {d['label']} — {sig['searches']} searches, {sig['comments']} comments{wow}")
        if d.get("hook"):
            lines.append(f'   Hook: "{d["hook"]}"')
    if briefing.get("open_gaps"):
        lines.append("")
        lines.append("Open gaps (no strong coverage yet):")
        for g in briefing["open_gaps"]:
            lines.append(f"   • {g['label']} ({g['demand']} asking)")
    if briefing.get("repromote"):
        r = briefing["repromote"]
        lines.append("")
        lines.append(f"♻️  Re-promote: {r['label']} — {r['why']}")
        if r.get("permalink"):
            lines.append(f"   {r['permalink']}")
    if briefing.get("drafted_post"):
        d = briefing["drafted_post"]
        lines.append("")
        lines.append(f"✍️  Drafted for you: {d['title']}")
        if d.get("hooks"):
            lines.append(f'   Hook: "{d["hooks"][0]}"')
        lines.append("   (open Sift to review & approve)")
    lines.append("")
    lines.append(f"Your archive: {briefing['archive_link']}")
    return "\n".join(lines)
