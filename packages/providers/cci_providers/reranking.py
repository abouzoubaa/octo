"""Rerank providers — the second-pass relevance model in hybrid retrieval.

First-pass (FTS + pgvector, fused with RRF) is recall-oriented; the reranker
reorders the merged candidates with a stronger query↔passage relevance signal.
Swappable like every other AI call: off | fake | llm | cross-encoder.
"""
from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod


class RerankProvider(ABC):
    name = "rerank"

    @abstractmethod
    def rerank(self, query: str, passages: list[str]) -> list[float]:
        """Return a relevance score per passage (higher = more relevant), aligned
        to the input order. Callers reorder by these scores."""


class FakeReranker(RerankProvider):
    """Deterministic lexical reranker — token-overlap (Jaccard-ish) with an IDF-free
    length normalisation. No network/model; a sensible offline default and testable."""

    name = "fake"

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        q = _tokens(query)
        if not q:
            return [0.0] * len(passages)
        scores = []
        for p in passages:
            pt = _tokens(p)
            if not pt:
                scores.append(0.0)
                continue
            overlap = len(q & pt)
            # precision×recall-ish, with a mild length penalty for very long passages
            score = (overlap / len(q)) * (overlap / math.sqrt(len(pt)))
            scores.append(score)
        return scores


class LLMReranker(RerankProvider):
    """LLM-scored relevance. Batches all passages into one call; falls back to a
    neutral score on any parse failure so retrieval never breaks."""

    name = "llm"

    SYSTEM = (
        "Score how well each numbered passage answers the query, 0.0–1.0. "
        'Return JSON: {"scores": [{"n": 1, "score": 0.0}, ...]} with one entry per passage.'
    )

    def __init__(self, llm):
        self._llm = llm

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        numbered = "\n".join(f"[{i + 1}] {p[:400]}" for i, p in enumerate(passages))
        try:
            raw = self._llm.complete(self.SYSTEM, f"Query: {query}\n\nPassages:\n{numbered}",
                                     json_output=True, max_tokens=400)
            data = json.loads(raw)
            scores = [0.0] * len(passages)
            for item in (data.get("scores", []) if isinstance(data, dict) else []):
                n = int(item.get("n", 0))
                if 1 <= n <= len(passages):
                    scores[n - 1] = float(item.get("score", 0.0))
            return scores
        except Exception:  # noqa: BLE001 — never let reranking break the query
            return [0.0] * len(passages)


class CrossEncoderReranker(RerankProvider):
    """Cross-encoder reranker (sentence-transformers). Strong + cheap at serve time;
    lazy-loads the model so it's only pulled in when configured."""

    name = "cross-encoder"

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model_name)

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return [float(s) for s in self._model.predict([(query, p) for p in passages])]


def _tokens(text: str) -> set[str]:
    return {t.strip(".,!?;:#()'\"").lower() for t in (text or "").split() if len(t) > 2}
