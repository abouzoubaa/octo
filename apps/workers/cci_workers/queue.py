"""RQ queues. Three lanes so a heavy backfill never starves the DM loop."""
from functools import lru_cache

import redis
from rq import Queue

from cci_core.config import get_settings

INGEST = "ingest"      # backfills, media downloads, transcribe/OCR/enrich/index
REALTIME = "realtime"  # webhook-driven comment → DM processing
PERIODIC = "periodic"  # radar clustering, digests, incremental syncs


@lru_cache
def get_redis() -> redis.Redis:
    return redis.from_url(get_settings().redis_url)


def get_queue(name: str = INGEST) -> Queue:
    return Queue(name, connection=get_redis())
