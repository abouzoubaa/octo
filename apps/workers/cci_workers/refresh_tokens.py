"""Refresh long-lived Instagram tokens before they expire (~60-day lifetime).

Without this, creators silently disconnect when their token lapses. Runs daily;
refreshes any token within the renewal window.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from cci_core.db import session_scope
from cci_core.instagram import refresh_long_lived
from cci_core.models import OAuthToken

log = logging.getLogger(__name__)

RENEW_WITHIN = timedelta(days=10)  # refresh when <10 days remain


def refresh_due_tokens() -> dict:
    """Refresh Instagram tokens nearing expiry. Idempotent; safe to run daily."""
    now = datetime.now(timezone.utc)
    cutoff = now + RENEW_WITHIN
    stats = {"checked": 0, "refreshed": 0, "failed": 0}

    with session_scope() as session:
        tokens = session.scalars(
            select(OAuthToken).where(
                OAuthToken.platform == "instagram",
                OAuthToken.expires_at.isnot(None),
                OAuthToken.expires_at <= cutoff,
            )
        ).all()
        for token in tokens:
            stats["checked"] += 1
            try:
                result = refresh_long_lived(token.access_token)
                token.access_token = result["access_token"]
                token.expires_at = now + timedelta(seconds=result.get("expires_in", 0))
                stats["refreshed"] += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("token refresh failed for creator %s: %s", token.creator_id, exc)
                stats["failed"] += 1
    log.info("token refresh: %s", stats)
    return stats
