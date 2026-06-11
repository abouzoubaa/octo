"""Instagram ingestion: posts + media + comments from day one (plan §4.1).

Comments are the cold-start fuel for Demand Radar — months of real questions
already sit under the posts, so they are first-class from the first sync.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.db import session_scope
from cci_core.instagram import InstagramClient
from cci_core.models import Comment, Creator, MediaAsset, OAuthToken, Post, PostStatus
from cci_core.privacy import pseudonymize
from cci_core.storage import ensure_bucket, store_media_from_url
from cci_retrieval.intent import INTENT_QUESTION, detect_intent

log = logging.getLogger(__name__)

MEDIA_TYPE_MAP = {"VIDEO": "reel", "IMAGE": "image", "CAROUSEL_ALBUM": "carousel"}


def _client_for(session: Session, creator: Creator) -> InstagramClient:
    token = session.scalar(
        select(OAuthToken).where(
            OAuthToken.creator_id == creator.id, OAuthToken.platform == "instagram"
        )
    )
    if token is None:
        raise RuntimeError(f"No Instagram token for creator {creator.handle}")
    return InstagramClient(access_token=token.access_token, request_delay_s=0.3)


def backfill_creator(creator_id: str, download_media: bool = True) -> dict:
    """Full backfill: every post, every comment. Idempotent (upserts by external id)."""
    stats = {"posts": 0, "comments": 0, "media": 0}
    with session_scope() as session:
        creator = session.get(Creator, creator_id)
        if creator is None or not creator.ig_user_id:
            raise RuntimeError("Creator missing or not connected to Instagram")
        client = _client_for(session, creator)
        for item in client.iter_media(creator.ig_user_id):
            post = _upsert_post(session, creator, item)
            stats["posts"] += 1
            if download_media and item.get("media_url") and item.get("media_type") == "VIDEO":
                stats["media"] += _store_media(session, post, item)
            stats["comments"] += sync_post_comments(session, client, creator, post)
            session.flush()
    log.info("backfill complete for %s: %s", creator_id, stats)
    return stats


def incremental_sync(creator_id: str) -> dict:
    """Scheduled sync: new posts, new comments (resume from watermarks), deletions."""
    stats = {"new_posts": 0, "new_comments": 0, "deleted": 0}
    with session_scope() as session:
        creator = session.get(Creator, creator_id)
        if creator is None or not creator.ig_user_id:
            return stats
        client = _client_for(session, creator)

        seen_external: set[str] = set()
        for item in client.iter_media(creator.ig_user_id):
            seen_external.add(item["id"])
            existing = session.scalar(
                select(Post).where(
                    Post.creator_id == creator.id,
                    Post.platform == "instagram",
                    Post.external_id == item["id"],
                )
            )
            if existing is None:
                post = _upsert_post(session, creator, item)
                stats["new_posts"] += 1
            else:
                post = existing
                if item.get("caption") != post.caption:  # edited caption → reindex later
                    post.caption = item.get("caption")
            stats["new_comments"] += sync_post_comments(session, client, creator, post)

        # detect deletions: active posts no longer returned by the API
        active = session.scalars(
            select(Post).where(
                Post.creator_id == creator.id,
                Post.platform == "instagram",
                Post.status == PostStatus.active,
            )
        ).all()
        from cci_retrieval.indexer import purge_post

        for post in active:
            if post.external_id not in seen_external:
                purge_post(session, post)
                stats["deleted"] += 1
    return stats


def sync_post_comments(session: Session, client: InstagramClient, creator: Creator,
                       post: Post) -> int:
    """Cursor-walk comments from the post's stored watermark; classify questions inline."""
    count = 0
    last_cursor = post.comment_sync_cursor
    for item, page_cursor in client.iter_comments(post.external_id, after=last_cursor):
        if _upsert_comment(session, creator, post, item):
            count += 1
        for reply in (item.get("replies") or {}).get("data", []):
            if _upsert_comment(session, creator, post, reply):
                count += 1
        last_cursor = page_cursor or last_cursor
    post.comment_sync_cursor = last_cursor
    post.last_comment_synced_at = datetime.now(timezone.utc)
    return count


def _upsert_post(session: Session, creator: Creator, item: dict) -> Post:
    post = session.scalar(
        select(Post).where(
            Post.creator_id == creator.id,
            Post.platform == "instagram",
            Post.external_id == item["id"],
        )
    )
    if post is None:
        post = Post(creator_id=creator.id, platform="instagram", external_id=item["id"])
        session.add(post)
    post.type = (
        "reel" if item.get("media_product_type") == "REELS"
        else MEDIA_TYPE_MAP.get(item.get("media_type", ""), "image")
    )
    post.caption = item.get("caption")
    post.permalink = item.get("permalink")
    post.media_url = item.get("media_url") or item.get("thumbnail_url")
    if item.get("timestamp"):
        post.posted_at = InstagramClient.parse_ts(item["timestamp"])
    session.flush()
    return post


def _store_media(session: Session, post: Post, item: dict) -> int:
    ensure_bucket()
    key = f"{post.creator_id}/{post.id}/source.mp4"
    try:
        store_media_from_url(item["media_url"], key)
    except Exception as exc:  # CDN URLs expire; sync again later
        log.warning("media download failed for %s: %s", post.id, exc)
        return 0
    session.add(MediaAsset(post_id=post.id, kind="video", storage_key=key))
    return 1


def _upsert_comment(session: Session, creator: Creator, post: Post, item: dict) -> bool:
    existing = session.scalar(
        select(Comment).where(
            Comment.creator_id == creator.id, Comment.external_id == item["id"]
        )
    )
    if existing is not None:
        return False
    author = (item.get("from") or {}).get("id", "anonymous")
    intent = detect_intent(item.get("text", ""))
    session.add(
        Comment(
            creator_id=creator.id,
            post_id=post.id,
            external_id=item["id"],
            author_pseudonym=pseudonymize(author, creator.id),
            text=item.get("text", ""),
            created_at=InstagramClient.parse_ts(item["timestamp"]) if item.get("timestamp") else None,
            is_question=intent.intent == INTENT_QUESTION,
            intent=intent.intent,
        )
    )
    return True
