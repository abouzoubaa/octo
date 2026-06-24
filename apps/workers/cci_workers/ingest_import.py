"""Creator-owned import ingestion (the cross-platform import mode).

When an API can't provide the full archive (the TikTok MVP path, or any import-mode
platform), the creator supplies content: an export ZIP, uploaded videos, transcript
files. We translate those into the SAME normalized Sift content and run the standard
transcribe/OCR/enrich/index pipeline — Demand Radar never knows the difference.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from cci_core.connectors import IngestMode, NormalizedContent, capabilities_for
from cci_core.connectors.base import CONTENT_READ
from cci_core.db import session_scope
from cci_core.language import detect_language
from cci_core.models import Creator, PlatformAccount, Post, Transcript

log = logging.getLogger(__name__)


def ingest_imported(creator_id: str, platform: str,
                    items: list[NormalizedContent | dict]) -> dict:
    """Create/upsert posts from creator-supplied content for `platform`. Idempotent
    by (creator, platform, external_id). Returns counts."""
    stats = {"platform": platform, "posts": 0, "transcripts": 0}
    if CONTENT_READ not in capabilities_for(platform):
        raise ValueError(f"platform '{platform}' has no content connector")

    with session_scope() as session:
        creator = session.get(Creator, creator_id)
        if creator is None:
            raise ValueError("creator not found")
        _ensure_account(session, creator_id, platform)

        for raw in items:
            item = _coerce(raw)
            post = session.scalar(select(Post).where(
                Post.creator_id == creator_id, Post.platform == platform,
                Post.external_id == item.external_id))
            if post is None:
                post = Post(creator_id=creator_id, platform=platform,
                            external_id=item.external_id)
                session.add(post)
                stats["posts"] += 1
            post.type = item.kind
            post.caption = item.caption
            post.permalink = item.permalink
            post.media_url = item.media_url
            post.posted_at = item.posted_at
            post.impressions = item.impressions
            if item.caption:
                post.language = detect_language(item.caption)
            session.flush()

            # a creator-supplied transcript skips the need for media transcription
            if item.transcript and not session.scalar(
                    select(Transcript).where(Transcript.post_id == post.id)):
                session.add(Transcript(
                    post_id=post.id, source="import", text=item.transcript,
                    segments=item.transcript_segments))
                stats["transcripts"] += 1
    log.info("imported %s content for %s: %s", platform, creator_id, stats)
    return stats


def _ensure_account(session, creator_id: str, platform: str) -> None:
    account = session.scalar(select(PlatformAccount).where(
        PlatformAccount.creator_id == creator_id, PlatformAccount.platform == platform))
    if account is None:
        account = PlatformAccount(creator_id=creator_id, platform=platform,
                                  mode=IngestMode.IMPORT, status="archive_only")
        session.add(account)
    account.capabilities = sorted(capabilities_for(platform))
    session.flush()


def _coerce(raw) -> NormalizedContent:
    if isinstance(raw, NormalizedContent):
        return raw
    if "external_id" not in raw:
        raise ValueError("import item missing 'external_id'")
    return NormalizedContent(
        external_id=str(raw["external_id"]),
        kind=raw.get("kind", "video"),
        caption=raw.get("caption"),
        permalink=raw.get("permalink"),
        media_url=raw.get("media_url"),
        transcript=raw.get("transcript"),
        transcript_segments=raw.get("transcript_segments"),
        impressions=raw.get("impressions"),
    )
