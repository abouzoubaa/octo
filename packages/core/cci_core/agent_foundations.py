"""Agent-layer foundations: state machine, outcome log, voice memory, offers, rules.

These are the shared memory/data layers every proactive Sift feature rides on
(agent roadmap §0). Kept deliberately small and additive — they don't change v1
behaviour, only record the data the agent learns from.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.models import (
    DEMAND_TRANSITIONS,
    CreatorRules,
    DemandState,
    DemandTopic,
    Offer,
    Outcome,
    VoiceExample,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------- demand state machine


class InvalidTransition(ValueError):
    """Raised when a demand-item state transition isn't allowed."""


def transition_demand(session: Session, topic: DemandTopic, to: DemandState,
                      *, published_post_id: str | None = None) -> DemandTopic:
    """Move a demand item to a new lifecycle state, enforcing valid transitions."""
    if to == topic.state:
        return topic  # self-transition is a no-op; don't re-stamp timestamps/marks
    allowed = DEMAND_TRANSITIONS.get(topic.state, set())
    if to not in allowed:
        raise InvalidTransition(f"{topic.state.value} → {to.value} is not allowed")
    topic.state = to
    topic.state_updated_at = utcnow()
    if to == DemandState.published and published_post_id:
        topic.published_post_id = published_post_id
    # keep the legacy creator_marked field consistent for existing UIs/metrics
    if to == DemandState.dismissed:
        topic.creator_marked = "not"
    elif to in (DemandState.idea, DemandState.drafting):
        topic.creator_marked = "useful"
    elif to == DemandState.published:
        topic.creator_marked = "made"
    session.flush()
    return topic


# --------------------------------------------------------------------- outcome log


def record_outcome(session: Session, creator_id: str, *, source: str,
                   question_text: str | None = None, query_id: str | None = None,
                   comment_id: str | None = None, demand_topic_id: str | None = None,
                   asker_pseudonym: str | None = None, answer_id: str | None = None,
                   served_state: str | None = None, confidence: float | None = None) -> Outcome:
    """Open an outcome record at the moment something is served."""
    outcome = Outcome(
        creator_id=creator_id, source=source, question_text=question_text,
        query_id=query_id, comment_id=comment_id, demand_topic_id=demand_topic_id,
        asker_pseudonym=asker_pseudonym, answer_id=answer_id,
        served_state=served_state, confidence=confidence, stage="served",
    )
    session.add(outcome)
    session.flush()
    return outcome


def advance_outcome(session: Session, outcome_id: str, *, stage: str | None = None,
                    creator_action: str | None = None, result: dict | None = None) -> Outcome | None:
    """Enrich an outcome as the interaction progresses (acted → clicked → converted → closed)."""
    outcome = session.get(Outcome, outcome_id)
    if outcome is None:
        return None
    if stage:
        outcome.stage = stage
    if creator_action:
        outcome.creator_action = creator_action
    if result:
        outcome.result = {**(outcome.result or {}), **result}
    outcome.updated_at = utcnow()
    session.flush()
    return outcome


# --------------------------------------------------------------------- voice memory


def capture_voice(session: Session, creator_id: str, kind: str, text: str, *,
                  prompt_context: str | None = None, original_draft: str | None = None,
                  source: str = "approved") -> VoiceExample:
    """Store an approved reply/hook/caption, or a draft edit, as on-voice few-shot fuel."""
    example = VoiceExample(
        creator_id=creator_id, kind=kind, text=text, prompt_context=prompt_context,
        original_draft=original_draft, source=source,
    )
    session.add(example)
    session.flush()
    return example


def voice_samples(session: Session, creator_id: str, kind: str | None = None,
                  limit: int = 6) -> list[VoiceExample]:
    """Most recent on-voice examples, optionally of one kind — for few-shot prompting."""
    stmt = select(VoiceExample).where(VoiceExample.creator_id == creator_id)
    if kind:
        stmt = stmt.where(VoiceExample.kind == kind)
    return list(session.scalars(stmt.order_by(VoiceExample.created_at.desc()).limit(limit)))


def voice_prompt_block(session: Session, creator_id: str, kind: str | None = None) -> str:
    """Render voice examples into a prompt fragment the LLM drafting layer can prepend.

    Style only — never a source of claims. Empty string when there's nothing yet.
    """
    samples = voice_samples(session, creator_id, kind)
    if not samples:
        return ""
    lines = ["The creator's voice — match this tone and phrasing (style only, never facts):"]
    for s in samples:
        lines.append(f'- "{s.text.strip()[:240]}"')
    return "\n".join(lines)


# --------------------------------------------------------------- offers & rules


def active_offers(session: Session, creator_id: str, now: datetime | None = None) -> list[Offer]:
    """Currently-active offers, highest priority first (for CTA/affiliate routing)."""
    now = now or utcnow()
    offers = session.scalars(
        select(Offer).where(Offer.creator_id == creator_id, Offer.active.is_(True))
        .order_by(Offer.priority.desc())
    ).all()
    live = []
    for o in offers:
        if o.starts_at and o.starts_at > now:
            continue
        if o.ends_at and o.ends_at < now:
            continue
        live.append(o)
    return live


def select_offer(session: Session, creator_id: str,
                 topics: list[str]) -> tuple[Offer | None, dict]:
    """Pick the best current offer AND record WHY it was selected (trust firewall):
    a topic match (with the overlapping topics) or a priority fallback. The reason is
    auditable — a creator/regulator can see the offer wasn't chosen for commission."""
    offers = active_offers(session, creator_id)
    if not offers:
        return None, {"basis": "none"}
    want = {t.lower() for t in topics or []}
    best, best_overlap, matched = None, 0, []
    for o in offers:
        otopics = {t.lower() for t in (o.topics or [])}
        overlap = want & otopics
        if len(overlap) > best_overlap:
            best, best_overlap, matched = o, len(overlap), sorted(overlap)
    if best is not None:
        return best, {"basis": "topic_match", "matched_topics": matched, "overlap": best_overlap}
    return offers[0], {"basis": "priority_fallback",
                       "note": "no topic match; highest-priority active offer"}


def best_offer_for_topics(session: Session, creator_id: str,
                          topics: list[str]) -> Offer | None:
    """Back-compat wrapper around select_offer (returns just the offer)."""
    return select_offer(session, creator_id, topics)[0]


def get_rules(session: Session, creator_id: str) -> CreatorRules:
    """Fetch (or lazily create) the creator's operating rules."""
    rules = session.get(CreatorRules, creator_id)
    if rules is None:
        rules = CreatorRules(creator_id=creator_id)
        session.add(rules)
        session.flush()
    return rules


def _mentions_topic(text: str, topics: list[str] | None) -> bool:
    """Whole-word topic match — avoids substring false positives ('ai' in 'rain',
    'med' in 'medium') and ignores empty/blank topic strings."""
    blob = (text or "").lower()
    for topic in topics or []:
        t = topic.strip().lower()
        if t and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", blob):
            return True
    return False


def is_taboo(rules: CreatorRules, text: str) -> bool:
    """Does this text touch a taboo topic the agent must never engage?"""
    return _mentions_topic(text, rules.taboo_topics)


def must_escalate(rules: CreatorRules, text: str) -> bool:
    """Does this text touch a topic that must always go to human review?"""
    return _mentions_topic(text, rules.escalate_topics)
