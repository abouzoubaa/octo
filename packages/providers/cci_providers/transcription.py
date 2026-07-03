"""Transcription providers: faster-whisper (local, near-zero cost) + Fake."""
from __future__ import annotations

from cci_providers.base import TranscriptionProvider, TranscriptResult, TranscriptSegment


class FasterWhisperTranscriber(TranscriptionProvider):
    name = "faster-whisper"

    def __init__(self, model_size: str = "small"):
        # Lazy import: the `ml` extra is optional outside worker images.
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_size, compute_type="auto")

    def transcribe(self, media_path: str) -> TranscriptResult:
        segments_iter, info = self._model.transcribe(media_path, vad_filter=True)
        segments = [
            TranscriptSegment(start=s.start, end=s.end, text=s.text.strip())
            for s in segments_iter
        ]
        text = " ".join(s.text for s in segments).strip()
        return TranscriptResult(
            text=text,
            segments=segments,
            quality=getattr(info, "language_probability", None),
        )


class FakeTranscriber(TranscriptionProvider):
    name = "fake"

    def transcribe(self, media_path: str) -> TranscriptResult:
        text = f"fake transcript for {media_path}"
        return TranscriptResult(
            text=text, segments=[TranscriptSegment(0.0, 1.0, text)], quality=1.0
        )
