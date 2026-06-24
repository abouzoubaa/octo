"""Weekly Demand Radar digest — the radar comes to the creator (plan §4.6).

Creators do not reliably visit dashboards, so the top evidence cards are pushed
weekly. v1 transport: rendered text handed to a pluggable sender (email/DM);
the console sender keeps local dev dependency-free.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from cci_core.db import session_scope
from cci_core.deep_links import search_link
from cci_core.models import Creator, DemandTopic

log = logging.getLogger(__name__)

TOP_N = 5


def render_digest(creator_id: str) -> str | None:
    iso = datetime.now(timezone.utc).isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    with session_scope() as session:
        creator = session.get(Creator, creator_id)
        if creator is None:
            return None
        cards = session.scalars(
            select(DemandTopic)
            .where(DemandTopic.creator_id == creator_id, DemandTopic.week == week)
            .order_by((DemandTopic.search_count + DemandTopic.comment_count).desc())
            .limit(TOP_N)
        ).all()
        if not cards:
            return None

        lines = [
            f"📡 Demand Radar — week {week} for @{creator.handle}",
            "What your audience wants — here's what to post next:",
            "",
        ]
        for i, card in enumerate(cards, 1):
            wow = f", {card.wow_change:+.0f}% WoW" if card.wow_change is not None else ""
            gap = " · CONTENT GAP" if (card.coverage or {}).get("gap") else ""
            lines.append(f"{i}. {card.label}")
            lines.append(f"   Signal: {card.search_count} searches, {card.comment_count} comments{wow}{gap}")
            if card.audience_language:
                lines.append(f'   They say: "{card.audience_language[0]}"')
            if card.recommendation:
                lines.append(f"   → Make: {card.recommendation}")
            if card.linked_products:
                names = ", ".join(p["name"] for p in card.linked_products)
                lines.append(f"   Linked products: {names}")
            lines.append("")
        lines.append(f"Your archive: {search_link(creator.handle)}")
        return "\n".join(lines)


def send_digest(creator_id: str) -> bool:
    """v1 sender: log to console/worker output. Swap for email/DM transport later."""
    digest = render_digest(creator_id)
    if digest is None:
        log.info("no radar cards this week for %s — no digest", creator_id)
        return False
    log.info("DIGEST for %s:\n%s", creator_id, digest)
    return True


def send_briefing(creator_id: str) -> bool:
    """Agent-layer (v1.5): the richer Briefing — top demand + hooks + gaps +
    re-promotion pick + one drafted post. Replaces the plain digest once the
    agent layer is enabled for a creator."""
    from cci_core.db import session_scope

    with session_scope() as session:
        from cci_agent.briefing import build_briefing, render_briefing_text

        briefing = build_briefing(session, creator_id, with_draft=True)
        if briefing is None:
            log.info("no demand signal this week for %s — no briefing", creator_id)
            return False
        log.info("BRIEFING for %s:\n%s", creator_id, render_briefing_text(briefing))
    return True
