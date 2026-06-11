"""Provider interfaces. Implementations live in sibling modules; selection in registry.py."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptResult:
    text: str
    segments: list[TranscriptSegment]
    quality: float | None = None


@dataclass
class OcrFragment:
    text: str
    confidence: float
    frame_ts: float | None = None


class LLMProvider(ABC):
    """Chat-style completion. `json_schema` asks for strict JSON output."""

    name: str = "llm"

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1024,
        json_output: bool = False,
    ) -> str: ...


class EmbeddingProvider(ABC):
    name: str = "embeddings"
    model: str = ""
    version: str = ""
    dims: int = 0

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class TranscriptionProvider(ABC):
    name: str = "transcription"

    @abstractmethod
    def transcribe(self, media_path: str) -> TranscriptResult: ...


class OCRProvider(ABC):
    name: str = "ocr"

    @abstractmethod
    def extract(self, media_path: str) -> list[OcrFragment]: ...
