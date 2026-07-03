"""Append-only event tracking — every metric in plan §8 needs events from day one."""
from sqlalchemy.orm import Session

from cci_core.models import Event

# Canonical event kinds (keep in sync with metrics in docs/IMPLEMENTATION_PLAN.md §8)
SEARCH = "search"
RESULT_CLICK = "result_click"
DEEPLINK_OPEN = "deeplink_open"
ANSWER_SHOWN = "answer_shown"
NO_ANSWER = "no_answer"
SHARE = "share"
DM_QUEUED = "dm_queued"
DM_SENT = "dm_sent"
DM_FALLBACK = "dm_fallback"
AFFILIATE_CLICK = "affiliate_click"
RADAR_MARKED = "radar_marked"


def track(session: Session, kind: str, creator_id: str | None = None, **payload) -> None:
    session.add(Event(creator_id=creator_id, kind=kind, payload=payload or None))
