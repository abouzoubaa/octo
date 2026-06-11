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

        # hourly incremental sync
        if now.minute < 5:
            periodic.enqueue("cci_workers.ingest_instagram.incremental_sync", creator_id)

        # weekly radar + digest: Monday 07:00 UTC
        if now.weekday() == 0 and now.hour == 7 and now.minute < 5:
            job = periodic.enqueue("cci_workers.radar.build_radar", creator_id)
            periodic.enqueue("cci_workers.digest.send_digest", creator_id, depends_on=job)


def schedule_forever(interval_s: int = 300) -> None:
    import time

    while True:
        tick()
        time.sleep(interval_s)
