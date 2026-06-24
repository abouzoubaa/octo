"""Public developer API (v3 · scale): read-only access to a creator's demand
intelligence, authenticated by an API key. The foundation for a dev ecosystem.

Scoped + revocable keys; aggregate/pseudonymous data only — same privacy posture
as the rest of Sift.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_agent.team import verify_api_key
from cci_core.db import get_db
from cci_core.models import ApiKey, DemandTopic

router = APIRouter(prefix="/v1/public", tags=["public-api"])


def require_api_key(authorization: str = Header(default=""),
                    db: Session = Depends(get_db)) -> ApiKey:
    key = authorization.removeprefix("Bearer ").strip()
    record = verify_api_key(db, key)
    if record is None:
        raise HTTPException(status_code=401, detail="invalid or revoked API key")
    return record


def _scoped(record: ApiKey, scope: str) -> None:
    # fail closed: a key with no scopes grants nothing (not everything)
    if not record.scopes or scope not in record.scopes:
        raise HTTPException(status_code=403, detail=f"key missing scope '{scope}'")


@router.get("/demand")
def demand(week: str | None = None, key: ApiKey = Depends(require_api_key),
           db: Session = Depends(get_db)) -> list[dict]:
    """Top demand topics for the key's creator (scope: demand:read)."""
    _scoped(key, "demand:read")
    stmt = select(DemandTopic).where(DemandTopic.creator_id == key.creator_id)
    if week:
        stmt = stmt.where(DemandTopic.week == week)
    rows = db.scalars(stmt.order_by(
        (DemandTopic.search_count + DemandTopic.comment_count).desc()).limit(50)).all()
    return [{"label": t.label, "searches": t.search_count, "comments": t.comment_count,
             "wow_change": t.wow_change, "state": t.state.value,
             "coverage_gap": (t.coverage or {}).get("gap")} for t in rows]
