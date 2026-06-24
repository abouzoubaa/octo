"""Audience intelligence (v2): persona segmentation, sentiment/emotion, trend
detection, content strategy advisor.

Grows Demand Radar from a weekly list into a chief of staff that segments, reads
emotion, and watches for trends. All aggregate and pseudonymous.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cci_core.models import Comment, DemandTopic, ExternalSignal, Query
from cci_providers import get_embedding_provider, get_llm

EMOTIONS = ("anxiety", "confusion", "excitement", "frustration", "neutral")
EMOTION_MARKERS = {
    "anxiety": ("worried", "scared", "afraid", "nervous", "anxious", "stress"),
    "confusion": ("confused", "don't understand", "unclear", "lost", "how do i even", "?!"),
    "excitement": ("love", "amazing", "can't wait", "excited", "🔥", "obsessed"),
    "frustration": ("frustrated", "annoyed", "not working", "tired of", "ugh", "still can't"),
}


# ------------------------------------------------------------- sentiment & emotion


def score_sentiment(text: str) -> str:
    """Lightweight emotion read — markers first, LLM only when ambiguous."""
    lowered = (text or "").lower()
    for emotion, markers in EMOTION_MARKERS.items():
        if any(m in lowered for m in markers):
            return emotion
    try:
        data = json.loads(get_llm().complete(
            "Classify the emotional tenor of an audience question into one of: "
            "anxiety, confusion, excitement, frustration, neutral. JSON: {\"emotion\": \"...\"}.",
            text or "", json_output=True, max_tokens=40))
        return data.get("emotion") if data.get("emotion") in EMOTIONS else "neutral"
    except Exception:  # noqa: BLE001
        return "neutral"


def sentiment_summary(session: Session, creator_id: str, days: int = 30) -> dict:
    """Distribution of emotions across recent question-comments — how it *feels*."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    comments = session.scalars(
        select(Comment).where(
            Comment.creator_id == creator_id, Comment.is_question.is_(True),
            Comment.ingested_at >= since)
    ).all()
    counts = dict.fromkeys(EMOTIONS, 0)
    for c in comments:
        emotion = c.sentiment or score_sentiment(c.text)
        if c.sentiment is None:
            c.sentiment = emotion  # backfill persisted read
        counts[emotion] = counts.get(emotion, 0) + 1
    total = sum(counts.values())
    return {"total": total, "counts": counts,
            "dominant": max(counts, key=counts.get) if total else "neutral"}


# --------------------------------------------------------------- persona segmentation


def segment_personas(session: Session, creator_id: str, k: int = 3,
                     min_size: int = 2) -> list[dict]:
    """Cluster the audience's questions into behaviour-based personas (e.g. beginners
    asking about deficits vs advanced asking about carb cycling)."""
    rows = session.scalars(
        select(Comment.text).where(
            Comment.creator_id == creator_id, Comment.is_question.is_(True))
    ).all()
    rows += list(session.scalars(select(Query.text).where(Query.creator_id == creator_id)))
    texts = [t.strip() for t in rows if t and t.strip()]
    if len(texts) < min_size:
        return []

    vectors = np.array(get_embedding_provider().embed(texts), dtype=float)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors = vectors / norms

    centroids, members = _kmeans(vectors, min(k, len(texts)))
    personas = []
    for ci, idxs in enumerate(members):
        if len(idxs) < min_size:
            continue
        sample = [texts[i] for i in idxs][:5]
        personas.append({
            "persona": _name_persona(sample),
            "size": len(idxs),
            "examples": sample,
        })
    personas.sort(key=lambda p: p["size"], reverse=True)
    return personas


def _kmeans(vectors: np.ndarray, k: int, iters: int = 10) -> tuple[np.ndarray, list[list[int]]]:
    """Tiny deterministic k-means (seed = first k points). No randomness (scripts
    forbid it and we want reproducible segments)."""
    centroids = vectors[:k].copy()
    members: list[list[int]] = [[] for _ in range(k)]
    for _ in range(iters):
        members = [[] for _ in range(k)]
        for i, v in enumerate(vectors):
            sims = centroids @ v
            members[int(np.argmax(sims))].append(i)
        for ci, idxs in enumerate(members):
            if idxs:
                c = vectors[idxs].mean(axis=0)
                centroids[ci] = c / (np.linalg.norm(c) or 1.0)
    return centroids, members


def _name_persona(samples: list[str]) -> str:
    try:
        data = json.loads(get_llm().complete(
            "Name this audience segment in 2-4 words from their questions. "
            "JSON: {\"name\": \"...\"}.",
            "\n".join(f"- {s}" for s in samples), json_output=True, max_tokens=40))
        return data.get("name") or "audience segment"
    except Exception:  # noqa: BLE001
        return samples[0][:40] if samples else "audience segment"


# ------------------------------------------------------------------ trend detection


def detect_trends(session: Session, creator_id: str, *, threshold: int = 3) -> list[dict]:
    """Rising themes week-over-week. Weekly by default; the proposal gates real-time
    spike alerts behind a query-volume threshold — enforced here."""
    topics = session.scalars(
        select(DemandTopic).where(DemandTopic.creator_id == creator_id,
                                  DemandTopic.wow_change.isnot(None))
    ).all()
    trends = []
    for t in topics:
        volume = t.search_count + t.comment_count
        if t.wow_change and t.wow_change > 0 and volume >= threshold:
            trends.append({"label": t.label, "wow_change": t.wow_change,
                           "volume": volume, "spike_alert": volume >= threshold * 5})
    trends.sort(key=lambda x: x["wow_change"], reverse=True)
    return trends


# --------------------------------------------------------------- strategy advisor


def strategy_advisor(session: Session, creator_id: str, question: str) -> dict:
    """Answer a strategic question grounded in Sift's accumulated data (demand
    volumes, gaps, sentiment) — expand vs double-down, which segment to serve."""
    topics = session.scalars(
        select(DemandTopic).where(DemandTopic.creator_id == creator_id)
        .order_by((DemandTopic.search_count + DemandTopic.comment_count).desc()).limit(10)
    ).all()
    n_external = session.scalar(
        select(func.count(ExternalSignal.id)).where(ExternalSignal.creator_id == creator_id)) or 0
    facts = [
        f"Top demand: {', '.join(t.label for t in topics[:5]) or 'none yet'}",
        f"Open gaps: {', '.join(t.label for t in topics if (t.coverage or {}).get('gap')) or 'none'}",
        f"Cross-platform signals captured: {n_external}",
        f"Dominant audience emotion: {sentiment_summary(session, creator_id)['dominant']}",
    ]
    try:
        data = json.loads(get_llm().complete(
            "You are a creator's content strategist. Answer the question using ONLY "
            "the supplied data facts; be concrete and concise. "
            "JSON: {\"recommendation\": \"...\", \"rationale\": \"...\"}.",
            f"Question: {question}\n\nData:\n" + "\n".join(f"- {f}" for f in facts),
            json_output=True, max_tokens=400))
    except Exception:  # noqa: BLE001
        data = {"recommendation": "Insufficient data — gather more demand signal first.",
                "rationale": ""}
    data["based_on"] = facts
    return data
