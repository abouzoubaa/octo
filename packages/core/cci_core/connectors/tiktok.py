"""TikTok connector — Sift's strongest market-facing wedge, but comment/message
access is conditional. So TikTok ships at TWO capability levels and the registry/UI
shows which is active rather than pretending every account has the full loop:

- Archive  (default): content + captions(transcribed) + search + citations + Demand
  Radar from imported/accessible interactions. No dependency on comment access.
- Full loop (where approved): comments, business messages, replies, publishing.

We never scrape — Archive mode is fed by the Content Posting/Display APIs for owned
accounts or by creator-supplied video import. Native ingest talks to the TikTok
Display API v2 through an injectable transport, so the path is tested without httpx.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cci_core.connectors.base import (
    CAPTIONS_READ,
    COMMENTS_READ,
    COMMENTS_REPLY,
    CONTENT_PUBLISH,
    CONTENT_READ,
    MEDIA_READ,
    MESSAGES_SEND,
    Connector,
    IngestMode,
    NormalizedContent,
    NormalizedInteraction,
    require,
)

# what an Archive-level TikTok account supports
ARCHIVE_CAPS = {CONTENT_READ, MEDIA_READ, CAPTIONS_READ, CONTENT_PUBLISH}
# additional capabilities a Full-loop (approved) account unlocks
FULL_LOOP_CAPS = ARCHIVE_CAPS | {COMMENTS_READ, COMMENTS_REPLY, MESSAGES_SEND}

_API = "https://open.tiktokapis.com/v2"
_VIDEO_FIELDS = "id,video_description,create_time,share_url,cover_image_url,duration"


class TikTokTransport:
    """Real HTTP transport (httpx) for the TikTok Display API. Faked in tests."""

    def __init__(self, base_url: str = _API, timeout: float = 20.0):
        self.base_url = base_url
        self.timeout = timeout

    def post(self, path: str, params: dict, json: dict, token: str | None) -> dict:
        import httpx

        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = httpx.post(f"{self.base_url}/{path}", params=params, json=json,
                       headers=headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()


def _parse_epoch(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


class TikTokConnector(Connector):
    platform = "tiktok"

    # backstops against an unbounded cursor walk
    _MAX_CONTENT_PAGES = 40
    _MAX_COMMENT_PAGES = 20

    def __init__(self, full_loop: bool = False, transport: Any | None = None):
        self.full_loop = full_loop
        self._t = transport or TikTokTransport()

    def capabilities(self) -> set[str]:
        return set(FULL_LOOP_CAPS if self.full_loop else ARCHIVE_CAPS)

    def ingest_modes(self) -> set[str]:
        # owned-account API where available, plus creator video import (the MVP path)
        return {IngestMode.NATIVE, IngestMode.IMPORT}

    # ---- helpers ---------------------------------------------------------------

    @staticmethod
    def _token(account) -> str | None:
        return getattr(account, "access_token", None)

    @staticmethod
    def _map_videos(data: dict) -> list[NormalizedContent]:
        out: list[NormalizedContent] = []
        for v in (data.get("data", {}) or {}).get("videos", []):
            vid = v.get("id")
            if not vid:
                continue
            out.append(NormalizedContent(
                external_id=str(vid), kind="short",
                caption=v.get("video_description"),
                permalink=v.get("share_url"),
                media_url=v.get("cover_image_url"),
                posted_at=_parse_epoch(v.get("create_time")),
            ))
        return out

    # ---- content ---------------------------------------------------------------

    def backfill_content(self, account) -> list[NormalizedContent]:
        out: list[NormalizedContent] = []
        cursor = None
        for _ in range(self._MAX_CONTENT_PAGES):
            items, cursor = self.sync_content(account, cursor)
            out.extend(items)
            if cursor is None:  # None = no more pages (a 0 cursor is still valid)
                break
        return out

    def sync_content(self, account, cursor: int | str | None = None):
        body: dict[str, Any] = {"max_count": 20}
        if cursor is not None:
            body["cursor"] = cursor
        data = self._t.post("video/list/", {"fields": _VIDEO_FIELDS}, body, self._token(account))
        payload = data.get("data", {}) or {}
        next_cursor = payload.get("cursor") if payload.get("has_more") else None
        return self._map_videos(data), next_cursor

    # ---- interactions (full-loop only) -----------------------------------------

    def backfill_interactions(self, account, content_external_id: str):
        if not self.full_loop:
            return []  # archive accounts have no comment access
        require(self, COMMENTS_READ)
        out: list[NormalizedInteraction] = []
        cursor = None
        for _ in range(self._MAX_COMMENT_PAGES):
            body: dict[str, Any] = {"video_id": content_external_id, "max_count": 50}
            if cursor is not None:
                body["cursor"] = cursor
            data = self._t.post("video/comment/list/", {}, body, self._token(account))
            payload = data.get("data", {}) or {}
            for c in payload.get("comments", []):
                cid = c.get("id")
                text = c.get("text")
                if not cid or not text:
                    continue
                out.append(NormalizedInteraction(
                    external_id=str(cid), text=text,
                    author_external_id=str(c.get("user", {}).get("id", "unknown")),
                    created_at=_parse_epoch(c.get("create_time")),
                    content_external_id=content_external_id, kind="comment",
                ))
            cursor = payload.get("cursor") if payload.get("has_more") else None
            if cursor is None:  # None = no more pages (a 0 cursor is still valid)
                break
        return out

    def reply_to_interaction(self, account, interaction_external_id: str, message: str):
        require(self, COMMENTS_REPLY)  # archive accounts can't reply
        return self._t.post("video/comment/reply/", {}, {
            "comment_id": interaction_external_id, "text": message}, self._token(account))
