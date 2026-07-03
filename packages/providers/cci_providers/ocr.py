"""OCR providers: PaddleOCR over sampled video keyframes / images + Fake.

OCR catches text-only or caption-burned reels — a large share of creator
content carries its key message as on-screen text (plan §4.2).
"""
from __future__ import annotations

from cci_providers.base import OcrFragment, OCRProvider


class PaddleOCRProvider(OCRProvider):
    name = "paddleocr"

    KEYFRAME_INTERVAL_S = 2.0  # sample a frame every 2s of video

    def __init__(self, lang: str = "en"):
        from paddleocr import PaddleOCR  # lazy: `ml` extra

        self._ocr = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)

    def extract(self, media_path: str) -> list[OcrFragment]:
        if media_path.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
            return self._extract_video(media_path)
        return self._run(media_path, frame_ts=None)

    def _extract_video(self, path: str) -> list[OcrFragment]:
        import cv2  # ships with paddleocr's deps

        cap = cv2.VideoCapture(path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = int(fps * self.KEYFRAME_INTERVAL_S)
        fragments: list[OcrFragment] = []
        seen: set[str] = set()
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % max(step, 1) == 0:
                ts = idx / fps
                for frag in self._run_array(frame, frame_ts=ts):
                    if frag.text not in seen:  # dedupe static overlays across frames
                        seen.add(frag.text)
                        fragments.append(frag)
            idx += 1
        cap.release()
        return fragments

    def _run(self, image_path: str, frame_ts: float | None) -> list[OcrFragment]:
        result = self._ocr.ocr(image_path, cls=True)
        return self._to_fragments(result, frame_ts)

    def _run_array(self, image, frame_ts: float | None) -> list[OcrFragment]:
        result = self._ocr.ocr(image, cls=True)
        return self._to_fragments(result, frame_ts)

    @staticmethod
    def _to_fragments(result, frame_ts: float | None) -> list[OcrFragment]:
        fragments = []
        for page in result or []:
            for line in page or []:
                text, conf = line[1]
                if conf >= 0.5 and len(text.strip()) > 1:
                    fragments.append(OcrFragment(text=text.strip(), confidence=conf, frame_ts=frame_ts))
        return fragments


class FakeOCR(OCRProvider):
    name = "fake"

    def extract(self, media_path: str) -> list[OcrFragment]:
        return [OcrFragment(text=f"fake on-screen text for {media_path}", confidence=0.99)]
