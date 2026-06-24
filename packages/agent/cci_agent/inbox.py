"""Engagement & inbox (v1.5): intent-labelled queue, bounded clarifying question,
no-answer waitlist, saved playbooks.

The inbox becomes a triage layer: comments + DM jobs sorted into one prioritised
queue with labels. Clarifying questions are bounded (one either/or), never open chat.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.models import Comment, DmJob, DmStatus, Playbook, WaitlistEntry
from cci_providers import get_llm

# inbox intent labels (a triage vocabulary on top of raw question/other detection)
LABELS = ("content_request", "purchase_intent", "support", "collab_lead", "other")
PRIORITY = {"purchase_intent": 0, "collab_lead": 1, "content_request": 2, "support": 3, "other": 4}

LABEL_SYSTEM = """\
Label one creator-inbox message into exactly one of:
content_request (wants a post / where's the X), purchase_intent (asking about
price, buying, signing up), support (a problem/complaint), collab_lead (brand or
partnership outreach), other. Return JSON: {"label": "...", "priority_reason": "..."}.\
"""

CLARIFY_SYSTEM = """\
The audience question is ambiguous for search. Produce ONE bounded either/or
clarifying question with two options — never open-ended. Return JSON:
{"question": "...", "options": ["A", "B"]}. Keep it to one short sentence.\
"""


def _keyword_label(text: str) -> str | None:
    """Fast keyword label; None when no marker matches (caller decides on LLM)."""
    lowered = (text or "").lower()
    if any(w in lowered for w in ("price", "cost", "how much", "buy", "sign up", "discount", "$")):
        return "purchase_intent"
    if any(w in lowered for w in ("collab", "partnership", "sponsor", "brand", "pr ", "gifting")):
        return "collab_lead"
    if any(w in lowered for w in ("broken", "refund", "not working", "problem", "issue", "help!")):
        return "support"
    if "?" in (text or "") or any(lowered.startswith(w) for w in ("where", "how", "what", "can you")):
        return "content_request"
    return None


def label_message(text: str, *, use_llm: bool = True) -> str:
    """Best-effort intent label for an inbox message. use_llm=False stays keyword-only
    (for list endpoints, to avoid a per-item network round-trip)."""
    label = _keyword_label(text)
    if label is not None:
        return label
    if not use_llm:
        return "other"
    try:
        data = json.loads(get_llm().complete(LABEL_SYSTEM, text or "", json_output=True, max_tokens=80))
        label = data.get("label") if isinstance(data, dict) else None
        return label if label in LABELS else "other"
    except Exception:  # noqa: BLE001
        return "other"


def labelled_inbox(session: Session, creator_id: str, limit: int = 50) -> list[dict]:
    """One prioritised, labelled queue across question-comments and pending DM jobs.

    Keyword-only labelling here (no per-item LLM call) to keep the list endpoint fast;
    DM-job comments are batch-loaded in one query to avoid N+1.
    """
    items: list[dict] = []

    comments = session.scalars(
        select(Comment).where(Comment.creator_id == creator_id, Comment.is_question.is_(True))
        .order_by(Comment.ingested_at.desc()).limit(limit)
    ).all()
    for c in comments:
        label = label_message(c.text, use_llm=False)
        items.append({"kind": "comment", "id": c.id, "text": c.text, "label": label,
                      "priority": PRIORITY.get(label, 4), "post_id": c.post_id})

    jobs = session.scalars(
        select(DmJob).where(DmJob.creator_id == creator_id,
                            DmJob.status == DmStatus.pending_approval)
        .order_by(DmJob.created_at.desc()).limit(limit)
    ).all()
    # batch-load the jobs' comments in one query (avoid N+1)
    comment_ids = [j.comment_id for j in jobs if j.comment_id]
    by_id = {}
    if comment_ids:
        by_id = {c.id: c for c in session.scalars(
            select(Comment).where(Comment.id.in_(comment_ids)))}
    for j in jobs:
        comment = by_id.get(j.comment_id) if j.comment_id else None
        label = label_message(comment.text if comment else "", use_llm=False)
        items.append({"kind": "dm_job", "id": j.id,
                      "text": comment.text if comment else None, "label": label,
                      "priority": PRIORITY.get(label, 4), "deep_link": j.deep_link})

    items.sort(key=lambda i: (i["priority"]))
    return items[:limit]


def bounded_clarify(question: str) -> dict | None:
    """One either/or clarifying question to disambiguate a vague search."""
    try:
        data = json.loads(get_llm().complete(CLARIFY_SYSTEM, question, json_output=True, max_tokens=120))
        if data.get("question") and len(data.get("options", [])) == 2:
            return {"question": data["question"], "options": data["options"]}
    except Exception:  # noqa: BLE001
        pass
    return None


# ----------------------------------------------------------------- waitlist


def add_to_waitlist(session: Session, creator_id: str, email: str, topic: str,
                    demand_topic_id: str | None = None) -> WaitlistEntry:
    """Capture a lead on a low-confidence (no strong answer) result."""
    entry = WaitlistEntry(creator_id=creator_id, email=email, topic=topic,
                          demand_topic_id=demand_topic_id)
    session.add(entry)
    session.flush()
    return entry


def waitlist_for_topic(session: Session, creator_id: str, demand_topic_id: str) -> list[WaitlistEntry]:
    return list(session.scalars(
        select(WaitlistEntry).where(
            WaitlistEntry.creator_id == creator_id,
            WaitlistEntry.demand_topic_id == demand_topic_id,
            WaitlistEntry.notified.is_(False),
        )
    ))


# ----------------------------------------------------------------- playbooks


def match_playbook(session: Session, creator_id: str, text: str,
                   intent: str | None = None) -> Playbook | None:
    """Find a saved playbook whose trigger/intent matches an incoming message."""
    playbooks = session.scalars(
        select(Playbook).where(Playbook.creator_id == creator_id, Playbook.active.is_(True))
    ).all()
    lowered = (text or "").lower()
    for pb in playbooks:
        if pb.intent and intent and pb.intent == intent:
            return pb
        for kw in (pb.trigger_keywords or []):
            if kw.lower() in lowered:
                return pb
    return None
