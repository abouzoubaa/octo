"""Brand & reputation (v2): crisis/sentiment-shift detection, voice consistency scoring.

A creator's income depends on trust and originality. These protect both.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.agent_foundations import voice_samples
from cci_core.models import Comment
from cci_providers import get_llm

NEGATIVE_EMOTIONS = ("anxiety", "frustration")


def detect_crisis(session: Session, creator_id: str, *, days: int = 3,
                  baseline_days: int = 30, spike_ratio: float = 2.0) -> dict:
    """Watch for a negative-sentiment spike: recent negative rate vs the baseline.

    Alerts early with the specific concerns. Sentiment is read lazily if absent.
    """
    from cci_agent.intelligence import score_sentiment

    now = datetime.now(timezone.utc)
    recent_since = now - timedelta(days=days)
    base_since = now - timedelta(days=baseline_days)

    base = session.scalars(
        select(Comment).where(Comment.creator_id == creator_id,
                              Comment.ingested_at >= base_since)
    ).all()
    if not base:
        return {"alert": False, "reason": "no recent comments"}

    def neg_rate(rows) -> tuple[float, list[str]]:
        neg = []
        for c in rows:
            emotion = c.sentiment or score_sentiment(c.text)
            if emotion in NEGATIVE_EMOTIONS:
                neg.append(c.text)
        return (len(neg) / len(rows) if rows else 0.0), neg

    recent = [c for c in base if c.ingested_at and c.ingested_at >= recent_since]
    baseline = [c for c in base if c.ingested_at and c.ingested_at < recent_since]
    recent_rate, recent_neg = neg_rate(recent)
    baseline_rate, _ = neg_rate(baseline)

    alert = bool(recent and recent_rate >= 0.3 and
                 (baseline_rate == 0 or recent_rate >= spike_ratio * baseline_rate))
    return {
        "alert": alert,
        "recent_negative_rate": round(recent_rate, 3),
        "baseline_negative_rate": round(baseline_rate, 3),
        "concerns": recent_neg[:5],
        "suggested_framework": (
            "Acknowledge the concern directly, clarify with a cited post, and offer a "
            "follow-up — don't go silent." if alert else None),
    }


def voice_consistency_score(session: Session, creator_id: str, text: str) -> dict:
    """Score new content (e.g. from a ghostwriter) against the creator's voice model,
    with deviation notes, before the creator reviews."""
    samples = voice_samples(session, creator_id, limit=8)
    if not samples:
        return {"score": None, "note": "no voice memory yet — approve a few replies first"}
    examples = "\n".join(f"- {s.text}" for s in samples)
    try:
        data = json.loads(get_llm().complete(
            "Score how well the candidate text matches the creator's voice (0-100) "
            "and note specific deviations. JSON: {\"score\": 0-100, \"deviations\": [\"...\"]}.",
            f"Creator's voice examples:\n{examples}\n\nCandidate:\n{text}",
            json_output=True, max_tokens=300))
        score = int(data.get("score", 0))
    except Exception:  # noqa: BLE001
        return {"score": None, "note": "scoring unavailable"}
    return {"score": score, "deviations": data.get("deviations", []),
            "on_voice": score >= 70}
