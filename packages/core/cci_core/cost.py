"""Per-creator AI cost metering + monthly caps.

LLM/transcription spend is a real operational risk at scale. We meter estimated
tokens per creator-scoped LLM call as events, expose the running monthly cost, and
let billing enforce a per-plan ceiling on creator-side expensive operations.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.config import get_settings
from cci_core.events import track
from cci_core.models import Event

LLM_TOKENS = "llm_tokens"  # event kind: payload {tokens, op}


def estimate_tokens(*texts: str) -> int:
    """Cheap token estimate (~4 chars/token) — good enough for budgeting."""
    return sum(len(t or "") for t in texts) // 4


def meter_llm(session: Session, creator_id: str | None, *texts: str, op: str = "llm") -> int:
    """Record estimated token usage for a creator-scoped LLM call."""
    if not creator_id:
        return 0
    tokens = estimate_tokens(*texts)
    track(session, LLM_TOKENS, creator_id, tokens=tokens, op=op)
    return tokens


def _month_start() -> datetime:
    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def monthly_tokens(session: Session, creator_id: str, *, op: str | None = None) -> int:
    """Month-to-date token total, aggregated in SQL — this runs on hot request paths
    (the public answer ceiling checks it per search), so fetching and decoding every
    event row in Python would grow linearly with the month's traffic."""
    from sqlalchemy import func

    stmt = select(func.coalesce(func.sum(
        Event.payload["tokens"].as_integer()), 0)).where(
        Event.creator_id == creator_id, Event.kind == LLM_TOKENS,
        Event.ts >= _month_start())
    if op is not None:
        stmt = stmt.where(Event.payload["op"].as_string() == op)
    return int(session.scalar(stmt) or 0)


def monthly_cost_cents(session: Session, creator_id: str, *, op: str | None = None) -> float:
    per_1k = get_settings().cost_per_1k_tokens_cents
    return round(monthly_tokens(session, creator_id, op=op) / 1000.0 * per_1k, 2)
