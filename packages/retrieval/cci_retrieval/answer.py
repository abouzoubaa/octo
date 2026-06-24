"""Grounded answer card (plan §4.4) — not open chat.

Rules:
- Generation uses ONLY retrieved chunks; every claim cites its chunk.
- Below the confidence threshold → explicit "no strong answer" state.
- The retrieval answer is separate from any creator-voice styling: correctness
  and citations first.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from cci_core.config import get_settings
from cci_core.models import Answer, AnswerState
from cci_core.safety import GUARD, neutralize, wrap_untrusted
from cci_providers import get_llm
from cci_retrieval.search import PostResult, retrieval_confidence, search

SYSTEM_PROMPT = """\
You write short, factual answer cards for a creator's content archive.
Rules — non-negotiable:
1. Use ONLY the numbered context passages below. Never add outside knowledge.
2. Every sentence must be supported by at least one passage; cite it as [n].
3. If the passages do not clearly answer the question, respond with exactly: NO_ANSWER
4. Maximum 4 sentences. No greetings, no filler, no opinions of your own.
Return JSON: {"answer": "...", "citations": [n, ...]} or {"answer": "NO_ANSWER"}.
""" + GUARD


@dataclass
class AnswerCard:
    state: str  # answered | no_strong_answer
    text: str | None
    citations: list[dict] = field(default_factory=list)  # {post_id, chunk_id, quote, n}
    confidence: float = 0.0
    results: list[PostResult] = field(default_factory=list)
    freshness: list[dict] = field(default_factory=list)  # superseded-source notes (set by serving layer)


def generate_answer(session: Session, creator_id: str, question: str) -> AnswerCard:
    s = get_settings()
    results = search(session, creator_id, question)
    confidence = retrieval_confidence(results)

    if not results or confidence < s.answer_min_confidence:
        return AnswerCard(state=AnswerState.no_strong_answer.value, text=None,
                          confidence=confidence, results=results)

    # number the evidence chunks for citation
    passages: list[tuple[int, PostResult, str, str]] = []  # (n, result, chunk_id, text)
    n = 1
    for result in results[:5]:
        for hit in result.evidence[:2]:
            passages.append((n, result, hit.chunk_id, hit.text))
            n += 1

    # the audience question is the highest-risk injection vector → fully delimited.
    # passages are defanged inline (markers neutralised) but keep the [n] format so
    # citation parsing still works.
    context = "\n".join(f"[{i}] {neutralize(text)}" for i, _, _, text in passages)
    user_msg = f"Question: {wrap_untrusted(question)}\n\nContext passages:\n{context}"

    raw = get_llm().complete(SYSTEM_PROMPT, user_msg, json_output=True, max_tokens=500)
    from cci_core.cost import meter_llm

    meter_llm(session, creator_id, user_msg, raw, op="answer")
    text, cited_ns = _parse_llm_answer(raw)

    if text is None:
        return AnswerCard(state=AnswerState.no_strong_answer.value, text=None,
                          confidence=confidence, results=results)

    by_n = {i: (r, cid, t) for i, r, cid, t in passages}
    citations = []
    for cn in cited_ns:
        if cn in by_n:
            result, chunk_id, chunk_text = by_n[cn]
            citations.append({
                "n": cn,
                "post_id": result.post_id,
                "chunk_id": chunk_id,
                "permalink": result.permalink,
                "quote": chunk_text[:240],
            })
    if not citations:  # an uncited answer is a hallucination risk — refuse it
        return AnswerCard(state=AnswerState.no_strong_answer.value, text=None,
                          confidence=confidence, results=results)

    return AnswerCard(state=AnswerState.answered.value, text=text,
                      citations=citations, confidence=confidence, results=results)


def persist_answer(session: Session, creator_id: str, card: AnswerCard,
                   query_id: str | None = None) -> Answer:
    answer = Answer(
        creator_id=creator_id,
        query_id=query_id,
        text=card.text,
        citations=card.citations or None,
        confidence=card.confidence,
        state=AnswerState(card.state),
        model=get_llm().name,
    )
    session.add(answer)
    session.flush()
    return answer


def _parse_llm_answer(raw: str) -> tuple[str | None, list[int]]:
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # tolerate plain-text answers with [n] citations from weaker models
        if "NO_ANSWER" in raw:
            return None, []
        ns = _extract_bracket_ns(raw)
        return (raw, ns) if ns else (None, [])
    answer = (data.get("answer") or "").strip()
    if not answer or answer == "NO_ANSWER":
        return None, []
    citations = [int(c) for c in data.get("citations", []) if str(c).isdigit()]
    if not citations:
        citations = _extract_bracket_ns(answer)
    return answer, citations


def _extract_bracket_ns(text: str) -> list[int]:
    import re

    return [int(m) for m in re.findall(r"\[(\d+)\]", text)]
