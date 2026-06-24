"""Versioned claim layer (Wave B): extract atomic claims, detect supersession,
and surface freshness so answers never confidently serve outdated advice.

This is the substantive half of "Canonical Answer Objects" — the freshness/
contradiction fix — without the full content-compiler reframe. It's additive: it
annotates answers, it does NOT change retrieval ranking (so the eval gate holds).
"""
from __future__ import annotations

import json
import logging

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.models import Claim, ClaimValidity, Post, Transcript
from cci_providers import get_embedding_provider, get_llm

log = logging.getLogger(__name__)

EXTRACT_SYSTEM = """\
Extract the atomic factual claims the creator personally asserts in this content
(advice, recommendations, positions). Skip questions and filler. Return JSON:
{"claims": [{"text": "one self-contained claim", "topic": "2-4 word topic",
 "validity": "current|dated|uncertain"}]}. Mark validity 'dated' if the claim is
explicitly time-bound, 'uncertain' if hedged, else 'current'. Max 8 claims.\
"""

SUPERSEDE_SYSTEM = """\
Two claims by the same creator on the same topic. Does the NEWER claim supersede
(replace/contradict/update) the OLDER one? Return JSON: {"supersedes": true|false}.
Only true if they genuinely conflict — not if they merely coexist.\
"""

SIM_THRESHOLD = 0.5  # cheap pre-filter for "about the same thing"; the LLM judge decides


def extract_claims(session: Session, post: Post, persist: bool = True) -> list[Claim]:
    """Extract atomic claims from a post's text. Idempotent: skips if already done."""
    if session.scalar(select(Claim.id).where(Claim.post_id == post.id).limit(1)):
        return []
    parts = [post.caption or ""]
    transcript = session.scalar(select(Transcript).where(Transcript.post_id == post.id))
    if transcript:
        parts.append(transcript.text)
    content = "\n".join(p for p in parts if p.strip())
    if not content.strip():
        return []

    try:
        data = json.loads(get_llm().complete(EXTRACT_SYSTEM, content[:4000],
                                             json_output=True, max_tokens=700))
        items = data.get("claims", []) if isinstance(data, dict) else []
    except Exception as exc:  # noqa: BLE001 — extraction is best-effort
        log.warning("claim extraction failed for %s: %s", post.id, exc)
        return []

    claims = []
    for item in items:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        validity = item.get("validity", "current")
        claim = Claim(
            creator_id=post.creator_id, post_id=post.id, text=text,
            topic=(item.get("topic") or "").strip()[:128] or None,
            source="transcript" if transcript else "caption",
            quote=text[:240], posted_at=post.posted_at,
            validity=ClaimValidity(validity if validity in
                                   ("current", "dated", "uncertain") else "current"),
        )
        if persist:
            session.add(claim)
        claims.append(claim)
    if persist:
        session.flush()
    return claims


def supersede(session: Session, old: Claim, new: Claim) -> None:
    """Mark `old` as superseded by `new`."""
    old.validity = ClaimValidity.superseded
    old.superseded_by = new.id
    session.flush()


def detect_contradictions(session: Session, creator_id: str) -> int:
    """Find claims on the same topic where a NEWER claim supersedes an older one.

    Groups by embedding similarity, judges conflicts with the LLM, and marks the
    older claim superseded. Returns the number of supersessions applied.
    """
    claims = session.scalars(
        select(Claim).where(Claim.creator_id == creator_id,
                            Claim.validity != ClaimValidity.superseded)
    ).all()
    if len(claims) < 2:
        return 0

    vectors = np.array(get_embedding_provider().embed([c.text for c in claims]), dtype=float)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors = vectors / norms

    def sort_key(c: Claim):
        return c.posted_at or c.created_at

    applied = 0
    n = len(claims)
    for i in range(n):
        for j in range(i + 1, n):
            if float(vectors[i] @ vectors[j]) < SIM_THRESHOLD:
                continue
            a, b = claims[i], claims[j]
            if a.validity == ClaimValidity.superseded or b.validity == ClaimValidity.superseded:
                continue
            older, newer = sorted((a, b), key=sort_key)
            if sort_key(older) == sort_key(newer):
                continue  # same time — can't say one supersedes the other
            try:
                data = json.loads(get_llm().complete(
                    SUPERSEDE_SYSTEM,
                    f"OLDER: {older.text}\nNEWER: {newer.text}",
                    json_output=True, max_tokens=60))
                if isinstance(data, dict) and data.get("supersedes") is True:
                    supersede(session, older, newer)
                    applied += 1
            except Exception:  # noqa: BLE001
                continue
    return applied


def claim_freshness(session: Session, post_ids: list[str]) -> list[dict]:
    """For a set of (cited) posts, surface any superseded claims so an answer can
    flag 'the creator later updated this advice' with the current version."""
    if not post_ids:
        return []
    superseded = session.scalars(
        select(Claim).where(Claim.post_id.in_(post_ids),
                            Claim.validity == ClaimValidity.superseded)
    ).all()
    notes = []
    for old in superseded:
        new = session.get(Claim, old.superseded_by) if old.superseded_by else None
        notes.append({
            "post_id": old.post_id, "topic": old.topic,
            "outdated": old.text,
            "current": new.text if new else None,
            "current_post_id": new.post_id if new else None,
        })
    return notes


def approve_claim(session: Session, claim_id: str) -> Claim | None:
    claim = session.get(Claim, claim_id)
    if claim is not None:
        claim.approved = True
    return claim
