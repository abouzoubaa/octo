"""Comment-to-DM pipeline (plan §4.5) — approval mode first, compliance bounds hard-coded.

Flow: webhook comment → intent → retrieval → DmJob (pending_approval) → operator
approves → dispatcher sends public reply + ONE private DM with answer + deep link.
Low confidence → friendly archive-link fallback, never a shaky answer in the
creator's voice. Rate cap (~200 DMs/hour) enforced by the dispatcher.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from cci_core.config import get_settings
from cci_core.db import session_scope
from cci_core.deep_links import answer_link, search_link
from cci_core.events import DM_FALLBACK, DM_QUEUED, DM_SENT, track
from cci_core.models import (
    AnswerState, Comment, Creator, DmJob, DmStatus, OAuthToken, Post, Query, QuerySource,
)
from cci_retrieval.answer import generate_answer, persist_answer
from cci_retrieval.intent import INTENT_QUESTION, INTENT_TRIGGER, detect_intent

log = logging.getLogger(__name__)


def handle_comment_event(creator_id: str, comment_external_id: str, comment_text: str,
                         author_id: str, media_external_id: str | None,
                         trigger_keywords: list[str] | None = None) -> str | None:
    """Webhook entry point. Returns the DmJob id if one was queued."""
    from cci_core.pii import redact_pii
    from cci_core.privacy import pseudonymize

    comment_text = redact_pii(comment_text) or ""  # GDPR: strip PII before storing

    with session_scope() as session:
        creator = session.get(Creator, creator_id)
        if creator is None:
            return None

        post = None
        if media_external_id:
            post = session.scalar(
                select(Post).where(
                    Post.creator_id == creator_id, Post.external_id == media_external_id
                )
            )

        comment = session.scalar(
            select(Comment).where(
                Comment.creator_id == creator_id, Comment.external_id == comment_external_id
            )
        )
        intent = detect_intent(comment_text, trigger_keywords)
        if comment is None:
            comment = Comment(
                creator_id=creator_id,
                post_id=post.id if post else None,
                external_id=comment_external_id,
                author_pseudonym=pseudonymize(author_id, creator_id),
                text=comment_text,
                created_at=datetime.now(timezone.utc),
                is_question=intent.intent == INTENT_QUESTION,
                intent=intent.intent,
            )
            session.add(comment)
            session.flush()

        if intent.intent not in (INTENT_QUESTION, INTENT_TRIGGER):
            return None

        # one reply per comment — ever (platform rule + politeness)
        existing = session.scalar(select(DmJob).where(DmJob.comment_id == comment.id))
        if existing is not None:
            return None

        job = _prepare_dm(session, creator, comment, comment_text)
        track(session, DM_QUEUED, creator_id, job_id=job.id, intent=intent.intent)
        return job.id


def _prepare_dm(session, creator: Creator, comment: Comment, question: str) -> DmJob:
    s = get_settings()
    card = generate_answer(session, creator.id, question)

    query = Query(
        creator_id=creator.id, source=QuerySource.comment, text=question,
        result_post_ids=[r.post_id for r in card.results], confidence=card.confidence,
    )
    session.add(query)
    session.flush()

    if card.state == AnswerState.answered.value and card.confidence >= s.dm_min_confidence:
        answer = persist_answer(session, creator.id, card, query_id=query.id)
        query.answer_id = answer.id
        link = answer_link(creator.handle, question, answer.id)
        cited = card.citations[0]["permalink"] if card.citations else None
        dm_text = f"{card.text}\n\nFull answer with sources: {link}"
        if cited:
            dm_text += f"\nOriginal post: {cited}"
        public_reply = "Sent you the answer in your DMs! 📩"
        status = DmStatus.pending_approval  # approval mode first — always
    else:
        # low confidence → archive-link fallback, never a shaky answer
        link = search_link(creator.handle, question)
        dm_text = (
            f"Great question! I couldn't pin down one exact post, but you can search "
            f"everything I've ever shared here: {link}"
        )
        public_reply = "Check your DMs — sent you where to find it! 🔎"
        status = DmStatus.pending_approval
        track(session, DM_FALLBACK, creator.id, comment_id=comment.id)

    job = DmJob(
        creator_id=creator.id,
        comment_id=comment.id,
        status=status,
        public_reply=public_reply,
        dm_text=dm_text,
        deep_link=link,
        answer_id=query.answer_id,
        confidence=card.confidence,
    )
    session.add(job)
    session.flush()
    return job


def dispatch_approved(creator_id: str) -> dict:
    """Send approved jobs, respecting the reply window and the hourly cap."""
    s = get_settings()
    stats = {"sent": 0, "expired": 0, "skipped_cap": 0, "failed": 0}
    now = datetime.now(timezone.utc)
    window = timedelta(days=s.dm_reply_window_days)

    with session_scope() as session:
        sent_last_hour = session.scalar(
            select(func.count(DmJob.id)).where(
                DmJob.creator_id == creator_id,
                DmJob.status == DmStatus.sent,
                DmJob.sent_at >= now - timedelta(hours=1),
            )
        ) or 0
        budget = max(s.dm_hourly_cap - sent_last_hour, 0)

        # comment-addressed jobs only. Agentic follow-up turns (comment_id IS NULL)
        # are addressed to a DM thread, not a comment — they need the dedicated
        # thread dispatcher (not yet built) and must not flow through here, where
        # there is no comment to key the send on and no window to enforce.
        jobs = session.scalars(
            select(DmJob)
            .where(DmJob.creator_id == creator_id, DmJob.status == DmStatus.approved,
                   DmJob.comment_id.isnot(None))
            .order_by(DmJob.created_at)
        ).all()

        token = session.scalar(
            select(OAuthToken).where(
                OAuthToken.creator_id == creator_id, OAuthToken.platform == "instagram"
            )
        )
        if token is None:
            return stats
        from cci_core.instagram import InstagramClient

        client = InstagramClient(access_token=token.access_token)

        for job in jobs:
            comment = session.get(Comment, job.comment_id)
            if comment is None:  # comment deleted since the job was queued
                job.status = DmStatus.failed
                job.error = "originating comment no longer exists"
                stats["failed"] += 1
                continue
            if comment.created_at and now - comment.created_at > window:
                job.status = DmStatus.expired  # outside the 7-day private-reply window
                stats["expired"] += 1
                continue
            if budget <= 0:
                stats["skipped_cap"] += 1  # viral post: the rest queue for next hour
                continue
            # enforce the connector capability for this comment's platform — a
            # platform without comment-reply / messaging (e.g. TikTok archive) must
            # not be sent through here. The capability registry is a real gate, not advisory.
            post = session.get(Post, comment.post_id) if comment.post_id else None
            platform = post.platform if post else "instagram"
            if not _can_dm(platform):
                job.status = DmStatus.failed
                job.error = f"{platform} connector lacks comment/message capability"
                stats["failed"] += 1
                continue
            try:
                if job.public_reply:
                    client.reply_to_comment(comment.external_id, job.public_reply)
                client.private_reply(comment.external_id, job.dm_text)
                job.status = DmStatus.sent
                job.sent_at = datetime.now(timezone.utc)
                budget -= 1
                stats["sent"] += 1
                track(session, DM_SENT, creator_id, job_id=job.id)
            except Exception as exc:  # noqa: BLE001
                log.warning("DM send failed for job %s: %s", job.id, exc)
                job.status = DmStatus.failed
                job.error = str(exc)[:500]
                stats["failed"] += 1
    return stats


def _can_dm(platform: str) -> bool:
    """The platform's connector must advertise comment-reply AND messaging to send."""
    from cci_core.connectors import capabilities_for
    from cci_core.connectors.base import COMMENTS_REPLY, MESSAGES_SEND

    caps = capabilities_for(platform)
    return COMMENTS_REPLY in caps and MESSAGES_SEND in caps
