"""Observability + protection: request IDs, structured logging, in-process metrics,
and a per-IP rate limiter for public endpoints.

The rate limiter is in-memory (per process) — fine for a single instance; swap for
a Redis-backed limiter when running multiple API replicas.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("cci.access")

# --- in-process metrics (Prometheus text exposition) ---------------------------
_counters: dict[str, int] = defaultdict(int)


def incr(metric: str, n: int = 1) -> None:
    _counters[metric] += n


def render_metrics() -> str:
    lines = ["# Sift API metrics"]
    for name, value in sorted(_counters.items()):
        lines.append(f"sift_{name} {value}")
    return "\n".join(lines) + "\n"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, time the request, log it, and count outcomes."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        start = time.perf_counter()
        incr("requests_total")
        try:
            response = await call_next(request)
        except Exception:
            incr("requests_error_total")
            log.exception("unhandled error rid=%s path=%s", request_id, request.url.path)
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000
        if response.status_code >= 500:
            incr("requests_5xx_total")
        elif response.status_code >= 400:
            incr("requests_4xx_total")
        response.headers["X-Request-ID"] = request_id
        log.info("rid=%s %s %s -> %d (%.1fms)", request_id, request.method,
                 request.url.path, response.status_code, elapsed_ms)
        return response


# --- per-IP sliding-window rate limiter ----------------------------------------
# In-memory, per process (single instance). For multiple API replicas, swap for a
# Redis-backed limiter. Idle IPs are swept and the key count is capped so a flood
# of distinct client IPs can't grow this map unboundedly.
_hits: dict[str, deque] = defaultdict(deque)
_MAX_TRACKED_IPS = 50_000
_last_sweep = 0.0


def _sweep(now: float) -> None:
    """Drop IPs whose window has fully aged out; hard-cap total tracked keys."""
    global _last_sweep
    if now - _last_sweep < 60.0 and len(_hits) < _MAX_TRACKED_IPS:
        return
    _last_sweep = now
    stale = [ip for ip, w in _hits.items() if not w or now - w[-1] > 60.0]
    for ip in stale:
        _hits.pop(ip, None)
    if len(_hits) >= _MAX_TRACKED_IPS:  # pathological: still too many → reset
        _hits.clear()


def rate_limit(request: Request) -> None:
    """FastAPI dependency: throttle a client IP on public endpoints."""
    from cci_core.config import get_settings

    limit = get_settings().public_rate_limit_per_min
    if limit <= 0:
        return
    ip = (request.client.host if request.client else "unknown")
    now = time.monotonic()
    _sweep(now)
    window = _hits[ip]
    while window and now - window[0] > 60.0:
        window.popleft()
    if len(window) >= limit:
        incr("rate_limited_total")
        raise HTTPException(status_code=429, detail="rate limit exceeded — slow down")
    window.append(now)


def configure_logging() -> None:
    from cci_core.config import get_settings

    if get_settings().log_json:
        fmt = '{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
    else:
        fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)


def init_sentry() -> bool:
    from cci_core.config import get_settings

    dsn = get_settings().sentry_dsn
    if not dsn:
        return False
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=dsn, traces_sample_rate=0.1)
        return True
    except Exception:  # noqa: BLE001 — never let telemetry break startup
        log.warning("sentry configured but sentry_sdk not installed")
        return False
