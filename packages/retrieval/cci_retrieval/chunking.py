"""Per-source chunkers (plan §4.3).

Targets ~200–400 tokens per chunk (approximated as words*0.75 tokens — close
enough for sizing). Transcript chunks overlap so spoken answers that straddle
a boundary stay retrievable, and carry a start timestamp for deep-linking into
the moment of the video.
"""
from __future__ import annotations

from dataclasses import dataclass

TARGET_WORDS = 220  # ≈ 290 tokens
MAX_WORDS = 320
OVERLAP_WORDS = 40


@dataclass
class RawChunk:
    source: str  # caption | transcript | ocr | summary
    text: str
    start_ts: float | None = None


def chunk_caption(caption: str) -> list[RawChunk]:
    return [RawChunk("caption", part) for part in _split_words(caption)]


def chunk_summary(summary: str) -> list[RawChunk]:
    return [RawChunk("summary", part) for part in _split_words(summary)]


def chunk_ocr(fragments: list[tuple[str, float | None]]) -> list[RawChunk]:
    """OCR lines are short; join into one chunk per ~TARGET_WORDS, keep first ts."""
    chunks: list[RawChunk] = []
    buf: list[str] = []
    buf_ts: float | None = None
    count = 0
    for text, ts in fragments:
        if not text.strip():
            continue
        if not buf:
            buf_ts = ts
        buf.append(text.strip())
        count += len(text.split())
        if count >= TARGET_WORDS:
            chunks.append(RawChunk("ocr", " · ".join(buf), start_ts=buf_ts))
            buf, count, buf_ts = [], 0, None
    if buf:
        chunks.append(RawChunk("ocr", " · ".join(buf), start_ts=buf_ts))
    return chunks


def chunk_transcript(segments: list[dict]) -> list[RawChunk]:
    """Overlapping windows over timed segments: [{start, end, text}]."""
    if not segments:
        return []
    chunks: list[RawChunk] = []
    window: list[dict] = []
    count = 0
    for seg in segments:
        window.append(seg)
        count += len(seg["text"].split())
        if count >= TARGET_WORDS:
            chunks.append(_window_chunk(window))
            # retain a tail for overlap
            tail: list[dict] = []
            tail_count = 0
            for s in reversed(window):
                tail_count += len(s["text"].split())
                tail.insert(0, s)
                if tail_count >= OVERLAP_WORDS:
                    break
            window, count = tail, tail_count
    if window and (not chunks or _window_text(window) != chunks[-1].text):
        chunks.append(_window_chunk(window))
    return chunks


def _window_chunk(window: list[dict]) -> RawChunk:
    return RawChunk("transcript", _window_text(window), start_ts=window[0]["start"])


def _window_text(window: list[dict]) -> str:
    return " ".join(s["text"].strip() for s in window).strip()


def _split_words(text: str) -> list[str]:
    """Split on paragraph boundaries first, then hard-wrap long paragraphs."""
    text = (text or "").strip()
    if not text:
        return []
    parts: list[str] = []
    current: list[str] = []
    count = 0
    for para in text.split("\n\n"):
        words = para.split()
        if count + len(words) > MAX_WORDS and current:
            parts.append(" ".join(current))
            current, count = [], 0
        if len(words) > MAX_WORDS:  # single huge paragraph → hard wrap
            for i in range(0, len(words), TARGET_WORDS):
                parts.append(" ".join(words[i : i + TARGET_WORDS]))
            continue
        current.extend(words)
        count += len(words)
    if current:
        parts.append(" ".join(current))
    return [p for p in parts if p]
