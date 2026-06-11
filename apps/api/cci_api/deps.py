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
