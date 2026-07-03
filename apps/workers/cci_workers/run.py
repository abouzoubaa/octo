"""Worker entrypoint: `cci-worker [queue ...]` — defaults to all three lanes."""
from __future__ import annotations

import logging
import sys

from rq import Worker

from cci_workers.queue import INGEST, PERIODIC, REALTIME, get_redis


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    queues = sys.argv[1:] or [REALTIME, INGEST, PERIODIC]
    worker = Worker(queues, connection=get_redis())
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
