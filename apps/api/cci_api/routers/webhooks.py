"""Instagram webhook receiver (plan §4.5: "Listen").

GET = subscription verification handshake; POST = comment events, routed to the
realtime queue so the webhook returns fast.
"""
from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from cci_core.config import get_settings
from cci_core.db import session_scope
from cci_core.models import Creator

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/instagram")
def verify(
    mode: str = Query(default="", alias="hub.mode"),
    challenge: str = Query(default="", alias="hub.challenge"),
    verify_token: str = Query(default="", alias="hub.verify_token"),
):
    if mode == "subscribe" and verify_token == get_settings().ig_webhook_verify_token:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/instagram")
async def receive(request: Request) -> dict:
    body = await request.body()
    _verify_signature(request.headers.get("x-hub-signature-256", ""), body)
    payload = await request.json()

    queued = 0
    for entry in payload.get("entry", []):
        ig_user_id = str(entry.get("id", ""))
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue
            value = change.get("value", {})
            if not _claim_event("instagram", value.get("id")):
                continue  # duplicate redelivery — Meta retries; process exactly once
            queued += _enqueue_comment(ig_user_id, value)
    return {"received": True, "queued": queued}


def _claim_event(platform: str, external_id: str | None) -> bool:
    """Record a webhook event id once; return False if already seen (idempotency)."""
    if not external_id:
        return True  # nothing to dedupe on — process it
    from sqlalchemy.exc import IntegrityError

    from cci_core.models import WebhookEvent

    try:
        with session_scope() as session:
            session.add(WebhookEvent(platform=platform, external_id=str(external_id)))
        return True
    except IntegrityError:
        return False  # unique (platform, external_id) violated → already processed


def _verify_signature(header: str, body: bytes) -> None:
    secret = get_settings().ig_app_secret
    if not secret:  # local dev without an app secret
        return
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(header, expected):
        raise HTTPException(status_code=403, detail="bad signature")


def _enqueue_comment(ig_user_id: str, value: dict) -> int:
    with session_scope() as session:
        creator = session.scalar(select(Creator).where(Creator.ig_user_id == ig_user_id))
        if creator is None:
            log.warning("webhook for unknown IG user %s", ig_user_id)
            return 0
        creator_id = creator.id

    from cci_workers.queue import REALTIME, get_queue

    get_queue(REALTIME).enqueue(
        "cci_workers.dm.handle_comment_event",
        creator_id,
        value.get("id", ""),
        value.get("text", ""),
        str((value.get("from") or {}).get("id", "anonymous")),
        (value.get("media") or {}).get("id"),
    )
    return 1
