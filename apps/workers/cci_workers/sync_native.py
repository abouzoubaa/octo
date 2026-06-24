"""Native connector sync — backfill content + interactions from a platform API.

Where ``ingest_import`` handles creator-supplied archives, this handles the *native*
ingest mode: ask a Connector for content and the comments under it, then map both
into the same Sift models the rest of the pipeline already understands (Post,
Comment) so Demand Radar treats a YouTube video exactly like an Instagram reel.

The connector talks to the platform through an injectable transport, so this whole
path is exercised in tests with a fake transport (no live API calls). The caller
supplies an ``account`` object exposing ``external_account_id`` and a decrypted
``access_token``; we never hand the connector a database handle or the token store.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select

from cci_agent.intelligence import score_sentiment
from cci_core.connectors import Connector, get_connector
from cci_core.connectors.base import COMMENTS_READ, CONTENT_READ, supports
from cci_core.db import session_scope
from cci_core.language import detect_language
from cci_core.models import Comment, Creator, OAuthToken, PlatformAccount, Post
from cci_core.pii import redact_pii
from cci_core.privacy import pseudonymize
from cci_retrieval.intent import INTENT_QUESTION, detect_intent

log = logging.getLogger(__name__)


def sync_native(creator_id: str, platform: str, *,
                connector: Connector | None = None, account=None) -> dict:
    """Backfill posts + comments from a native connector. Idempotent by
    (creator, platform, external_id) for posts and (creator, external_id) for
    comments. Returns counts."""
    connector = connector or get_connector(platform)
    if connector is None or not supports(connector, CONTENT_READ):
        raise ValueError(f"platform '{platform}' has no native content connector")
    stats = {"platform": platform, "posts": 0, "comments": 0, "questions": 0}
    read_comments = supports(connector, COMMENTS_READ)

    with session_scope() as session:
        creator = session.get(Creator, creator_id)
        if creator is None:
            raise ValueError("creator not found")
        account = account or _resolve_account(session, creator_id, platform)
        _ensure_account(session, creator_id, platform, account)

        for item in connector.backfill_content(account):
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
            post.posted_at = item.posted_at
            if item.caption:
                post.language = detect_language(item.caption)
            session.flush()

            if read_comments:
                # one comments-disabled video (YouTube 403) or a transient fetch
                # error must not abort the whole channel backfill — skip and go on.
                try:
                    interactions = connector.backfill_interactions(account, item.external_id)
                except Exception as exc:  # noqa: BLE001
                    log.warning("interactions fetch failed for %s/%s: %s",
                                platform, item.external_id, exc)
                    continue
                for it in interactions:
                    created, is_question = _upsert_comment(session, creator_id, post.id, it)
                    if created:
                        stats["comments"] += 1
                        stats["questions"] += int(is_question)

        # stamp the sync so the dashboard can show "last synced" per connector
        pa = session.scalar(select(PlatformAccount).where(
            PlatformAccount.creator_id == creator_id, PlatformAccount.platform == platform))
        if pa is not None:
            pa.last_synced_at = datetime.now(timezone.utc)
    log.info("native sync %s for %s: %s", platform, creator_id, stats)
    return stats


def _upsert_comment(session, creator_id: str, post_id: str, it) -> tuple[bool, bool]:
    """Returns (created, is_question). Idempotent by (creator, external_id)."""
    existing = session.scalar(select(Comment).where(
        Comment.creator_id == creator_id, Comment.external_id == it.external_id))
    if existing is not None:
        return False, False
    text = redact_pii(it.text or "") or ""  # GDPR: strip PII before storing
    intent = detect_intent(text)
    is_question = intent.intent == INTENT_QUESTION
    session.add(Comment(
        creator_id=creator_id, post_id=post_id, external_id=it.external_id,
        author_pseudonym=pseudonymize(it.author_external_id, creator_id),
        text=text, created_at=it.created_at, is_question=is_question,
        intent=intent.intent,
        sentiment=score_sentiment(text, use_llm=False) if is_question else None,
    ))
    return True, is_question


def _resolve_account(session, creator_id: str, platform: str):
    """Build the connector's account view from the stored PlatformAccount + the
    decrypted OAuth token (EncryptedString decrypts transparently on read)."""
    pa = session.scalar(select(PlatformAccount).where(
        PlatformAccount.creator_id == creator_id, PlatformAccount.platform == platform))
    tok = session.scalar(select(OAuthToken).where(
        OAuthToken.creator_id == creator_id, OAuthToken.platform == platform))
    return SimpleNamespace(
        external_account_id=(pa.external_account_id if pa else None),
        access_token=(tok.access_token if tok else None))


def _ensure_account(session, creator_id: str, platform: str, account) -> None:
    from cci_core.connectors import capabilities_for

    pa = session.scalar(select(PlatformAccount).where(
        PlatformAccount.creator_id == creator_id, PlatformAccount.platform == platform))
    if pa is None:
        pa = PlatformAccount(creator_id=creator_id, platform=platform, mode="native",
                             status="connected",
                             external_account_id=getattr(account, "external_account_id", None))
        session.add(pa)
    pa.capabilities = sorted(capabilities_for(platform))
    session.flush()
