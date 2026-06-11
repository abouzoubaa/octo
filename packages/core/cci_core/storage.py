"""S3-compatible object storage for downloaded media (MinIO locally, anything in prod)."""
from __future__ import annotations

import io
from functools import lru_cache
from urllib.parse import urlparse

import httpx
from minio import Minio

from cci_core.config import get_settings


@lru_cache
def get_storage() -> Minio:
    s = get_settings()
    parsed = urlparse(s.s3_endpoint)
    return Minio(
        parsed.netloc,
        access_key=s.s3_access_key,
        secret_key=s.s3_secret_key,
        secure=parsed.scheme == "https",
    )


def ensure_bucket() -> None:
    s = get_settings()
    client = get_storage()
    if not client.bucket_exists(s.s3_bucket):
        client.make_bucket(s.s3_bucket)


def store_media_from_url(url: str, key: str) -> str:
    """Download a media URL (e.g. IG CDN) and persist it; returns the object key."""
    s = get_settings()
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as resp:
        resp.raise_for_status()
        data = resp.read()
    get_storage().put_object(
        s.s3_bucket,
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=resp.headers.get("content-type", "application/octet-stream"),
    )
    return key


def fetch_media(key: str) -> bytes:
    s = get_settings()
    resp = get_storage().get_object(s.s3_bucket, key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()
