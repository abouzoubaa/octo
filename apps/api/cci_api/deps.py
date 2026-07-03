"""Shared FastAPI dependencies."""
from fastapi import Depends, Header, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.config import get_settings
from cci_core.db import get_db
from cci_core.models import Creator


def require_admin(authorization: str = Header(default="")) -> None:
    """v1 single-operator auth: `Authorization: Bearer <CCI_ADMIN_TOKEN>`."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token or token != get_settings().admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")


def get_creator(handle: str = Path(...), db: Session = Depends(get_db)) -> Creator:
    creator = db.scalar(select(Creator).where(Creator.handle == handle))
    if creator is None:
        raise HTTPException(status_code=404, detail="creator not found")
    return creator


def safe_enqueue(queue, func_path: str, *args, **kwargs):
    """Enqueue but surface a Redis outage as 503 (queue unavailable) instead of a
    leaked 500 — an offline queue is a transient infra problem, not a client error."""
    import redis

    try:
        return queue.enqueue(func_path, *args, **kwargs)
    except redis.exceptions.RedisError:
        raise HTTPException(status_code=503, detail="job queue temporarily unavailable")


def ensure_creator(db: Session, creator_id: str) -> Creator:
    """Operator routes key on a raw creator_id — assert it exists so writes against a
    bad id 404 cleanly instead of silently no-op'ing (FK at commit) or leaking a 500."""
    creator = db.get(Creator, creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="creator not found")
    return creator
