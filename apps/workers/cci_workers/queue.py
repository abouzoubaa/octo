"""RQ queues. Three lanes so a heavy backfill never starves the DM loop."""
from functools import lru_cache

import redis
from rq import Queue, Retry

from cci_core.config import get_settings

INGEST = "ingest"      # backfills, media downloads, transcribe/OCR/enrich/index
REALTIME = "realtime"  # webhook-driven comment → DM processing
PERIODIC = "periodic"  # radar clustering, digests, incremental syncs

# default retry policy: 3 attempts with backoff. Jobs that exhaust retries land in
# RQ's FailedJobRegistry (the dead-letter queue) for inspection/requeue.
DEFAULT_RETRY = Retry(max=3, interval=[10, 60, 300])


@lru_cache
def get_redis() -> redis.Redis:
    return redis.from_url(get_settings().redis_url)


def get_queue(name: str = INGEST) -> Queue:
    return Queue(name, connection=get_redis())


def enqueue(name: str, func_path: str, *args, retry: Retry | None = DEFAULT_RETRY,
            **kwargs):
    """Enqueue with a retry policy by default (transient failures self-heal; terminal
    ones dead-letter to the FailedJobRegistry)."""
    return get_queue(name).enqueue(func_path, *args, retry=retry, **kwargs)
