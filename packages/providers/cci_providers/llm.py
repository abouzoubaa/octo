"""LLM providers: Anthropic, OpenAI-compatible (covers LiteLLM/vLLM/Ollama gateways), Fake."""
from __future__ import annotations

import json

import httpx

from cci_providers.base import LLMProvider


class AnthropicLLM(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def complete(self, system: str, user: str, *, max_tokens: int = 1024,
                 json_output: bool = False) -> str:
        if json_output:
            system += "\nRespond with valid JSON only — no prose, no code fences."
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


class OpenAICompatibleLLM(LLMProvider):
    """Any OpenAI-compatible endpoint: OpenAI, LiteLLM proxy, vLLM, Ollama, …"""

    name = "openai-compatible"

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def complete(self, system: str, user: str, *, max_tokens: int = 1024,
                 json_output: bool = False) -> str:
        body: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_output:
            body["response_format"] = {"type": "json_object"}
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class FakeLLM(LLMProvider):
    """Deterministic stand-in for development and tests — no network, no cost.

    Heuristics are intentionally simple; anything depending on real model quality
    must be exercised through the eval harness against a live provider.
    """

    name = "fake"

    def complete(self, system: str, user: str, *, max_tokens: int = 1024,
                 json_output: bool = False) -> str:
        if json_output:
            return self._fake_json(system, user)
        # Extractive "answer": echo the most relevant-looking sentence of the context.
        lines = [ln.strip() for ln in user.splitlines() if len(ln.strip()) > 40]
        return lines[0] if lines else "No content available."

    @staticmethod
    def _fake_json(system: str, user: str) -> str:
        sys_l = system.lower()
        if "answer card" in sys_l:
            # extractive grounded answer: quote the first context passage, cite [1]
            import re

            passages = re.findall(r"^\[(\d+)\] (.+)$", user, flags=re.MULTILINE)
            if not passages:
                return json.dumps({"answer": "NO_ANSWER"})
            n, text = passages[0]
            sentence = text.split(". ")[0][:200]
            return json.dumps({"answer": f"{sentence}. [{n}]", "citations": [int(n)]})
        if "enrich" in sys_l:
            words = [w.strip(".,!?#").lower() for w in user.split() if len(w) > 5]
            return json.dumps({
                "summary": user[:200],
                "topics": sorted(set(words[:5])),
                "keywords": sorted(set(words[:10])),
                "product_mentions": [],
                "location_mentions": [],
            })
        if "intent" in sys_l:
            is_q = "?" in user or any(
                user.lower().startswith(w) for w in ("how", "what", "where", "when", "why", "can", "do")
            )
            return json.dumps({"intent": "question" if is_q else "other",
                               "confidence": 0.9 if is_q else 0.6})
        if "cluster" in sys_l or "radar" in sys_l:
            return json.dumps({"label": user.splitlines()[0][:80] if user else "general",
                               "recommendation": "Make a post answering the most repeated question."})
        # --- agent layer feature shapes (offline fakes) ---
        first_line = (user.splitlines()[0][:120] if user else "")
        if "content brief" in sys_l:
            return json.dumps({"angle": first_line or "the core question",
                               "audience_phrasing": [first_line] if first_line else [],
                               "covers_gap": "the specific sub-question", "cta": "Follow for more"})
        if "reel" in sys_l:
            return json.dumps({"hooks": [first_line or "Here's what nobody tells you"],
                               "script": user[:300], "caption": user[:200], "cta": "Save this"})
        if "format" in sys_l:  # repurposing
            return json.dumps({"format": "ig_carousel", "content": user[:400]})
        if "series" in sys_l:
            return json.dumps({"parts": ["Part 1: the basics", "Part 2: the mistakes"],
                               "faq_post": "Top 5 questions answered",
                               "dm_followup": "Want the checklist?", "offer_tie_in": ""})
        if "strateg" in sys_l:
            return json.dumps({"recommendation": "Double down on the highest-demand gap.",
                               "rationale": "Demand is concentrated and under-served."})
        if "clarifying" in sys_l:
            return json.dumps({"question": "Which did you mean?", "options": ["A", "B"]})
        if "inbox message" in sys_l:
            return json.dumps({"label": "content_request", "priority_reason": "asks for a post"})
        if "emotional tenor" in sys_l or "emotion" in sys_l:
            return json.dumps({"emotion": "neutral"})
        if "audience segment" in sys_l:
            return json.dumps({"name": first_line[:40] or "audience segment"})
        if "sponsorship pitch" in sys_l:
            return json.dumps({"pitch": "Your audience is actively asking about this — "
                                        "partner with us to answer them."})
        if "voice" in sys_l:
            return json.dumps({"score": 80, "deviations": []})
        if "passage" in sys_l and "score" in sys_l:  # reranker
            import re

            q_match = re.search(r"Query:\s*(.+)", user)
            q_tokens = set((q_match.group(1) if q_match else "").lower().split())
            passages = re.findall(r"^\[(\d+)\] (.+)$", user, flags=re.MULTILINE)
            scores = []
            for n, text in passages:
                pt = set(text.lower().split())
                overlap = len(q_tokens & pt) / (len(q_tokens) or 1)
                scores.append({"n": int(n), "score": round(min(overlap, 1.0), 3)})
            return json.dumps({"scores": scores})
        if "thumbnail" in sys_l:
            return json.dumps({"concepts": [
                {"text_overlay": first_line[:40] or "WATCH THIS", "layout": "face",
                 "why": "faces lift CTR"}]})
        if "skill-development" in sys_l or "development plan" in sys_l:
            return json.dumps({"one_year": ["improve hooks"], "three_year": ["expand formats"],
                               "five_year": ["build a team"]})
        return json.dumps({"result": user[:100]})
