"""Revenue (v2): sponsor matchmaker + pitch, affiliate optimisation.

Turns declared intent (every question) into income proof and optimised placement.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cci_core.models import DemandTopic, Event, ProductLink
from cci_providers import get_llm


def sponsor_report(session: Session, creator_id: str, topic_label: str | None = None) -> dict:
    """Demand-as-proof one-pager for brands: '412 questions about creatine this
    month, up 67%', plus a pitch drafted in the audience's own language."""
    stmt = select(DemandTopic).where(DemandTopic.creator_id == creator_id)
    if topic_label:
        stmt = stmt.where(DemandTopic.label.ilike(f"%{topic_label}%"))
    topics = session.scalars(
        stmt.order_by((DemandTopic.search_count + DemandTopic.comment_count).desc())
    ).all()
    if not topics:
        return {"proof": [], "pitch": None}

    proof = [{
        "topic": t.label,
        "questions": t.search_count + t.comment_count,
        "wow_change": t.wow_change,
        "audience_language": (t.audience_language or [])[:3],
    } for t in topics[:5]]

    top = proof[0]
    try:
        pitch = json.loads(get_llm().complete(
            "Draft a 3-sentence brand sponsorship pitch using the audience's own "
            "phrasing and the demand numbers. JSON: {\"pitch\": \"...\"}.",
            f"Top topic: {top['topic']} — {top['questions']} questions"
            + (f", up {top['wow_change']:.0f}%" if top.get('wow_change') else "")
            + f"\nAudience says: {top['audience_language']}",
            json_output=True, max_tokens=300)).get("pitch")
    except Exception:  # noqa: BLE001
        pitch = None
    return {"proof": proof, "pitch": pitch}


def affiliate_optimisation(session: Session, creator_id: str, days: int = 30) -> list[dict]:
    """Surface placement winners: which posts convert affiliate clicks best, so the
    creator can move links to higher-converting content."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    # affiliate clicks per product from the event log
    rows = session.execute(
        select(Event.payload).where(
            Event.creator_id == creator_id, Event.kind == "affiliate_click",
            Event.ts >= since)
    ).all()
    clicks: dict[str, int] = {}
    for (payload,) in rows:
        pid = (payload or {}).get("product_id")
        if pid:
            clicks[pid] = clicks.get(pid, 0) + 1

    # how many posts each product is currently mapped to (reach proxy)
    suggestions = []
    for product_id, n_clicks in sorted(clicks.items(), key=lambda x: -x[1]):
        n_posts = session.scalar(
            select(func.count(ProductLink.id)).where(ProductLink.product_id == product_id)) or 0
        suggestions.append({
            "product_id": product_id, "clicks": n_clicks, "mapped_posts": n_posts,
            "suggestion": ("high demand, few placements — map to more posts"
                           if n_clicks >= 3 and n_posts <= 1 else "placement looks balanced"),
        })
    return suggestions
