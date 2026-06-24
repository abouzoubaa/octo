"""Periodic job registration (RQ scheduler).

- incremental sync: hourly per active creator
- DM dispatcher: every 5 minutes (drains approved jobs within the hourly cap)
- Demand Radar build + digest: weekly (Monday 07:00 UTC)
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from cci_core.db import session_scope
from cci_core.models import Creator, CreatorStatus
from cci_workers.queue import PERIODIC, REALTIME, get_queue


def tick() -> None:
    """Idempotent scheduler tick — enqueue due jobs for every active creator.

    Run from cron / RQ scheduler every 5 minutes; cheap no-op when nothing is due.
    """
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        creator_ids = list(
            session.scalars(select(Creator.id).where(Creator.status == CreatorStatus.active))
        )

    realtime = get_queue(REALTIME)
    periodic = get_queue(PERIODIC)

    for creator_id in creator_ids:
        # DM dispatcher: every tick (5 min) — respects its own hourly cap
        realtime.enqueue("cci_workers.dm.dispatch_approved", creator_id)

        # hourly incremental sync (Instagram's richer legacy path: media + watermarks)
        if now.minute < 5:
            periodic.enqueue("cci_workers.ingest_instagram.incremental_sync", creator_id)

        # weekly radar + digest: Monday 07:00 UTC
        if now.weekday() == 0 and now.hour == 7 and now.minute < 5:
            job = periodic.enqueue("cci_workers.radar.build_radar", creator_id)
            periodic.enqueue("cci_workers.digest.send_digest", creator_id, depends_on=job)

    # hourly native-connector incremental sync (YouTube etc.). Instagram is covered
    # by its own incremental_sync above; this picks up every other authorized native
    # account in one bulk query so the loop above stays cheap.
    if now.minute < 5:
        enqueue_native_syncs(periodic)

    # daily OAuth token refresh (global, not per-creator): 06:00 UTC
    if now.hour == 6 and now.minute < 5:
        periodic.enqueue("cci_workers.refresh_tokens.refresh_due_tokens")


def enqueue_native_syncs(periodic) -> int:
    """Enqueue a native sync for every active creator's authorized native account
    (excluding Instagram, which has its own richer path). Returns the count enqueued."""
    from cci_core.connectors import capabilities_for
    from cci_core.connectors.base import CONTENT_READ
    from cci_core.models import OAuthToken, PlatformAccount

    with session_scope() as session:
        rows = session.execute(
            select(PlatformAccount.creator_id, PlatformAccount.platform)
            .join(Creator, Creator.id == PlatformAccount.creator_id)
            .join(OAuthToken, (OAuthToken.creator_id == PlatformAccount.creator_id)
                  & (OAuthToken.platform == PlatformAccount.platform))
            .where(Creator.status == CreatorStatus.active,
                   PlatformAccount.mode == "native")
        ).all()

    n = 0
    for creator_id, platform in rows:
        if platform == "instagram":
            continue  # covered by ingest_instagram.incremental_sync
        if CONTENT_READ not in capabilities_for(platform):
            continue
        periodic.enqueue("cci_workers.sync_native.sync_native", creator_id, platform)
        n += 1
    return n


def schedule_forever(interval_s: int = 300) -> None:
    import time

    while True:
        tick()
        time.sleep(interval_s)
