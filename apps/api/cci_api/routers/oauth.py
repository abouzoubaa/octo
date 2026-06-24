"""OAuth onboarding (plan §"data reality"): Instagram Login + YouTube.

Flow: GET /oauth/instagram/start?handle=alex → redirect to consent → Instagram
redirects back to /oauth/instagram/callback?code=…&state=… → we exchange the code
for a long-lived token, store it encrypted, and create/link the creator.

State is an HMAC-signed token carrying the intended handle, so the callback can't
be forged or replayed across creators.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.config import get_settings
from cci_core.db import get_db
from cci_core.instagram import (
    InstagramClient,
    authorize_url,
    exchange_code_for_token,
    exchange_for_long_lived,
)
from cci_core.models import Creator, CreatorStatus, OAuthToken

log = logging.getLogger(__name__)
router = APIRouter(prefix="/oauth", tags=["oauth"])


def _redirect_uri() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/oauth/instagram/callback"


STATE_TTL_SECONDS = 600  # a state is valid for 10 minutes (limits replay)


def _state_key() -> bytes:
    s = get_settings()
    # a dedicated signing secret, not the admin token; falls back with a salt
    return (s.oauth_state_secret or (s.admin_token + ":oauth")).encode()


def _sign_state(handle: str, issued: int | None = None) -> str:
    issued = issued if issued is not None else int(_now())
    payload = f"{handle}.{issued}"
    mac = hmac.new(_state_key(), payload.encode(), hashlib.sha256).hexdigest()  # full tag
    return f"{payload}.{mac}"


def _verify_state(state: str) -> str | None:
    parts = state.rsplit(".", 2)
    if len(parts) != 3:
        return None
    handle, issued, _mac = parts
    if not hmac.compare_digest(_sign_state(handle, int(issued)) if issued.isdigit() else "", state):
        return None
    if int(_now()) - int(issued) > STATE_TTL_SECONDS:  # expired
        return None
    return handle


def _now() -> float:
    import time

    return time.time()


@router.get("/instagram/start")
def instagram_start(handle: str = Query(..., min_length=1, max_length=64)):
    """Begin connecting an Instagram account for `handle`."""
    if not get_settings().ig_app_id:
        raise HTTPException(status_code=503, detail="Instagram app not configured")
    url = authorize_url(_redirect_uri(), state=_sign_state(handle.strip().lower()))
    return RedirectResponse(url, status_code=302)


@router.get("/instagram/callback")
def instagram_callback(code: str = Query(default=""), state: str = Query(default=""),
                       error: str = Query(default=""), db: Session = Depends(get_db)):
    """Exchange the code for a long-lived token and onboard the creator."""
    if error:
        raise HTTPException(status_code=400, detail=f"authorization denied: {error}")
    handle = _verify_state(state)
    if handle is None:
        raise HTTPException(status_code=400, detail="invalid or forged state")
    if not code:
        raise HTTPException(status_code=400, detail="missing code")

    try:
        short = exchange_code_for_token(code, _redirect_uri())
        long_lived = exchange_for_long_lived(short["access_token"])
    except Exception as exc:  # noqa: BLE001
        log.warning("IG token exchange failed for %s: %s", handle, exc)
        raise HTTPException(status_code=502, detail="token exchange failed")

    access_token = long_lived["access_token"]
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=long_lived.get("expires_in", 0))
    profile = InstagramClient(access_token=access_token).me()

    creator = db.scalar(select(Creator).where(Creator.handle == handle))
    if creator is None:
        creator = Creator(handle=handle, display_name=profile.get("username", handle),
                          status=CreatorStatus.active)
        db.add(creator)
        db.flush()
    creator.ig_user_id = str(profile["id"])
    creator.status = CreatorStatus.active

    token = db.scalar(select(OAuthToken).where(
        OAuthToken.creator_id == creator.id, OAuthToken.platform == "instagram"))
    if token is None:
        token = OAuthToken(creator_id=creator.id, platform="instagram")
        db.add(token)
    token.access_token = access_token  # encrypted at rest via EncryptedString
    token.expires_at = expires_at
    token.scopes = "instagram_business_basic,_manage_comments,_manage_messages"

    # kick off the first backfill so the archive starts filling immediately
    try:
        from cci_workers.queue import INGEST, get_queue

        get_queue(INGEST).enqueue("cci_workers.ingest_instagram.backfill_creator",
                                  creator.id, job_timeout=3600 * 6)
    except Exception as exc:  # noqa: BLE001 — onboarding shouldn't fail if Redis is down
        log.warning("could not enqueue backfill for %s: %s", handle, exc)

    base = get_settings().public_base_url.rstrip("/")
    return RedirectResponse(f"{base}/studio/{creator.id}", status_code=302)
