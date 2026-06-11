"""Embedding providers: OpenAI-compatible + deterministic Fake for tests/dev."""
from __future__ import annotations

import hashlib
import math

import httpx

from cci_providers.base import EmbeddingProvider


class OpenAICompatibleEmbeddings(EmbeddingProvider):
    name = "openai-compatible"

    def __init__(self, api_key: str, model: str, dims: int, version: str = "1",
                 base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.model = model
        self.dims = dims
        self.version = version
        self.base_url = base_url.rstrip("/")

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = httpx.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts, "dimensions": self.dims},
            timeout=120,
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]


class FakeEmbeddings(EmbeddingProvider):
    """Deterministic bag-of-words hash embedding.

    Real enough for tests: similar texts (shared tokens) get similar vectors,
    so cosine ranking behaves sensibly without any model.
    """

    name = "fake"
    model = "fake-bow"
    version = "1"

    def __init__(self, dims: int = 256):
        self.dims = dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        tokens = [t.strip(".,!?;:#()'\"").lower() for t in text.split()]
        for tok in tokens:
            if not tok:
                continue
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % self.dims] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
