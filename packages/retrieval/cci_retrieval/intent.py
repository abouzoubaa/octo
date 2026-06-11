"""Comment intent detection — routes comment-to-DM (plan §4.5).

Two stages: a cheap deterministic pre-filter (trigger keywords, question marks)
and an LLM classification only for the ambiguous middle. Trigger keywords are
per-post CTAs ("Comment PLAN and I'll send the exact routine").
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from cci_providers import get_llm

QUESTION_STARTERS = (
    "how", "what", "where", "when", "why", "which", "who", "can ", "could ",
    "do ", "does ", "did ", "is ", "are ", "should ", "would ", "any ",
)
NOISE_MARKERS = ("🔥", "❤", "😍", "👏", "first!", "nice", "love this", "amazing", "great post")

INTENT_QUESTION = "question"
INTENT_TRIGGER = "trigger"
INTENT_OTHER = "other"

SYSTEM_PROMPT = """\
You classify Instagram comment intent for a creator's archive assistant.
Categories: "question" (asks for information/content the creator may have answered),
"other" (praise, emoji, tagging friends, spam).
Return JSON: {"intent": "...", "confidence": 0.0-1.0}.\
"""


@dataclass
class IntentResult:
    intent: str
    confidence: float
    matched_trigger: str | None = None


def detect_intent(text: str, trigger_keywords: list[str] | None = None) -> IntentResult:
    stripped = (text or "").strip()
    lowered = stripped.lower()
    if not stripped:
        return IntentResult(INTENT_OTHER, 1.0)

    # 1) per-post CTA triggers ("Comment PLAN ...") — exact word match, highest priority
    for kw in trigger_keywords or []:
        if kw.lower() in lowered.split() or lowered == kw.lower():
            return IntentResult(INTENT_TRIGGER, 1.0, matched_trigger=kw)

    # 2) obvious noise
    if len(stripped) < 4 or any(m in lowered for m in NOISE_MARKERS):
        return IntentResult(INTENT_OTHER, 0.95)

    # 3) obvious questions
    if "?" in stripped or lowered.startswith(QUESTION_STARTERS) or "where's" in lowered:
        return IntentResult(INTENT_QUESTION, 0.9)

    # 4) ambiguous → LLM
    try:
        raw = get_llm().complete(SYSTEM_PROMPT, stripped, json_output=True, max_tokens=100)
        data = json.loads(raw)
        intent = data.get("intent", INTENT_OTHER)
        if intent not in (INTENT_QUESTION, INTENT_OTHER):
            intent = INTENT_OTHER
        return IntentResult(intent, float(data.get("confidence", 0.5)))
    except Exception:
        return IntentResult(INTENT_OTHER, 0.3)  # fail closed: never DM on a guess
