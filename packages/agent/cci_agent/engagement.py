"""Engagement (v2): reply assistant, agentic DM follow-up, community delegation,
Loop-Closer, 'not now' queue.

Comment-to-DM grows from one auto-reply into an approval-mode assistant. Every
guardrail from v1 carries: approval by default, one creator-initiated message per
comment within 7 days, re-contact only inside that window or an opted-in channel.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cci_core.agent_foundations import voice_prompt_block
from cci_core.config import get_settings
from cci_core.deep_links import answer_link, search_link
from cci_core.models import (
    Comment,
    DeferredItem,
    DemandState,
    DemandTopic,
    DmJob,
    DmStatus,
)
from cci_retrieval.answer import generate_answer, persist_answer


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------- reply assistant


def draft_reply(session: Session, creator_id: str, creator_handle: str,
                question: str) -> dict:
    """Draft a grounded, on-voice reply to a question — for comments or DMs.

    Correctness/citations come from retrieval; voice is a post-retrieval layer.
    Low confidence → archive-link fallback, never a fabricated answer.
    """
    s = get_settings()
    card = generate_answer(session, creator_id, question)
    voice = voice_prompt_block(session, creator_id, kind="dm")  # tone hint (style only)

    if card.state == "answered" and card.confidence >= s.dm_min_confidence:
        answer = persist_answer(session, creator_id, card)
        link = answer_link(creator_handle, question, answer.id)
        cited = card.citations[0]["permalink"] if card.citations else None
        text = f"{card.text}\n\nFull answer with sources: {link}"
        if cited:
            text += f"\nOriginal post: {cited}"
        return {"text": text, "state": "answered", "confidence": card.confidence,
                "answer_id": answer.id, "deep_link": link, "voice_hint": bool(voice)}

    link = search_link(creator_handle, question)
    return {"text": (f"Great question! I couldn't pin down one exact post, but you can "
                     f"search everything here: {link}"),
            "state": "fallback", "confidence": card.confidence,
            "answer_id": None, "deep_link": link, "voice_hint": bool(voice)}


# -------------------------------------------------------- agentic DM (multi-turn)


def handle_dm_followup(session: Session, creator_id: str, creator_handle: str,
                       parent_job_id: str, fan_reply: str) -> str | None:
    """The fan replied to a DM → use their reply as the next turn (within the
    7-day window). Creates a follow-up DmJob in approval mode. Returns its id."""
    parent = session.get(DmJob, parent_job_id)
    if parent is None:
        return None
    # the fan replying re-opens the window; still approval-gated. Follow-up turns
    # carry no comment_id (not creator-initiated) — the thread is tracked via
    # parent_job_id, which keeps the one-reply-per-comment unique constraint intact.
    card = draft_reply(session, creator_id, creator_handle, fan_reply)
    job = DmJob(
        creator_id=creator_id,
        comment_id=None,
        status=DmStatus.pending_approval,
        dm_text=card["text"],
        deep_link=card["deep_link"],
        answer_id=card["answer_id"],
        confidence=card["confidence"],
        parent_job_id=parent_job_id,
        turn=parent.turn + 1,
    )
    session.add(job)
    session.flush()
    return job.id


def can_auto_approve(session: Session, creator_id: str, intent: str | None) -> bool:
    """'Always approve this question type' — only if the creator opted that intent
    in AND the citation gate has passed (checked by the dispatcher, not here)."""
    from cci_core.agent_foundations import get_rules

    rules = get_rules(session, creator_id)
    return bool(intent and intent in (rules.auto_approve_types or []))


def bulk_approve(session: Session, creator_id: str, job_ids: list[str]) -> int:
    """Creator bulk-approves a day's queue in one action."""
    n = 0
    for jid in job_ids:
        job = session.get(DmJob, jid)
        if job and job.creator_id == creator_id and job.status == DmStatus.pending_approval:
            job.status = DmStatus.approved
            n += 1
    return n


# --------------------------------------------------------------- community delegation


def delegation_candidate(session: Session, creator_id: str, comment: Comment) -> Comment | None:
    """If a follower already answered this well on the same post, prefer liking
    their comment to spending the creator's single-DM quota. Returns the candidate."""
    if comment.post_id is None:
        return None
    siblings = session.scalars(
        select(Comment).where(
            Comment.creator_id == creator_id,
            Comment.post_id == comment.post_id,
            Comment.id != comment.id,
            Comment.is_question.is_(False),
        )
    ).all()
    q_tokens = {w for w in comment.text.lower().split() if len(w) > 3}
    best, best_score = None, 0.0
    for sib in siblings:
        if len(sib.text) < 40:  # a real answer has substance
            continue
        s_tokens = {w for w in sib.text.lower().split() if len(w) > 3}
        overlap = len(q_tokens & s_tokens) / (len(q_tokens) or 1)
        if overlap > best_score:
            best, best_score = sib, overlap
    return best if best_score >= 0.25 else None


# ------------------------------------------------------------------- Loop-Closer


def close_loop(session: Session, topic: DemandTopic, creator_handle: str) -> list[str]:
    """When the creator publishes what an asker requested, notify the original
    askers — compliant only inside the 7-day window. Creates pending-approval
    DM jobs (never auto-sends). Returns the job ids created; advances state."""
    s = get_settings()
    window = timedelta(days=s.dm_reply_window_days)
    now = utcnow()
    new_jobs: list[DmJob] = []

    for comment_id in (topic.asker_comment_ids or []):
        comment = session.get(Comment, comment_id)
        if comment is None or comment.created_at is None:
            continue
        if now - comment.created_at > window:  # outside the compliant window
            continue
        # one reply per comment — skip if we already have a job for it
        existing = session.scalar(select(DmJob).where(DmJob.comment_id == comment.id))
        if existing is not None:
            continue
        link = search_link(creator_handle, topic.label)
        job = DmJob(
            creator_id=topic.creator_id,
            comment_id=comment.id,
            status=DmStatus.pending_approval,
            public_reply=None,
            dm_text=(f"You asked about this a while back — I just posted about it! "
                     f"Here it is: {link}"),
            deep_link=link,
        )
        session.add(job)
        new_jobs.append(job)

    if topic.state == DemandState.published:
        from cci_core.agent_foundations import InvalidTransition, transition_demand

        try:
            transition_demand(session, topic, DemandState.loop_closed)
        except InvalidTransition:
            pass  # state pre-checked; only a genuine bad transition lands here
    session.flush()  # flush so the jobs have ids before we return them
    return [j.id for j in new_jobs]


# ------------------------------------------------------------- 'not now' queue


def defer_question(session: Session, creator_id: str, question: str, *,
                   weeks: int = 6, comment_id: str | None = None,
                   demand_topic_id: str | None = None) -> DeferredItem:
    item = DeferredItem(
        creator_id=creator_id, question=question, comment_id=comment_id,
        demand_topic_id=demand_topic_id, remind_at=utcnow() + timedelta(weeks=weeks),
    )
    session.add(item)
    session.flush()
    return item


def due_deferrals(session: Session, creator_id: str, now: datetime | None = None) -> list[DeferredItem]:
    """Deferred questions whose reminder time has arrived — surface + draft now."""
    now = now or utcnow()
    return list(session.scalars(
        select(DeferredItem).where(
            DeferredItem.creator_id == creator_id,
            DeferredItem.status == "waiting",
            DeferredItem.remind_at <= now,
        )
    ))


def pending_dm_count(session: Session, creator_id: str) -> int:
    return session.scalar(
        select(func.count(DmJob.id)).where(
            DmJob.creator_id == creator_id, DmJob.status == DmStatus.pending_approval)
    ) or 0
