"""YouTube connector — best deep, citable source material; strong comments.

Caption download requires creator authorization for the channel, which fits Sift's
creator-connected model.

This is a *native* connector: it talks to the YouTube Data API v3 over HTTP through
an injectable transport, so the network layer can be faked in tests (no live calls).
The orchestration layer attaches a decrypted OAuth ``access_token`` to the account
object it passes in; the connector itself never touches the database or the token
store.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from cci_core.connectors.base import (
    ANALYTICS_READ,
    CAPTIONS_READ,
    COMMENTS_READ,
    COMMENTS_REPLY,
    CONTENT_PUBLISH,
    CONTENT_READ,
    EVENTS_WEBHOOK,
    MEDIA_READ,
    Connector,
    IngestMode,
    NormalizedContent,
    NormalizedInteraction,
    require,
)

_API = "https://www.googleapis.com/youtube/v3"


class YouTubeTransport:
    """Real HTTP transport (httpx). Swapped for a fake in tests so the connector is
    exercised end-to-end without network access."""

    def __init__(self, base_url: str = _API, timeout: float = 20.0):
        self.base_url = base_url
        self.timeout = timeout

    def _headers(self, token: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"} if token else {}

    def get(self, path: str, params: dict, token: str | None) -> dict:
        import httpx

        r = httpx.get(f"{self.base_url}/{path}", params=params,
                      headers=self._headers(token), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, params: dict, json: dict, token: str | None) -> dict:
        import httpx

        r = httpx.post(f"{self.base_url}/{path}", params=params, json=json,
                       headers=self._headers(token), timeout=self.timeout)
        r.raise_for_status()
        return r.json()


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class YouTubeConnector(Connector):
    platform = "youtube"

    def __init__(self, transport: Any | None = None):
        self._t = transport or YouTubeTransport()

    def capabilities(self) -> set[str]:
        # comments + creator-authorized captions + analytics + upload notifications.
        # No private messaging surface like IG DMs.
        return {
            CONTENT_READ, MEDIA_READ, CAPTIONS_READ, COMMENTS_READ, COMMENTS_REPLY,
            CONTENT_PUBLISH, EVENTS_WEBHOOK, ANALYTICS_READ,
        }

    def ingest_modes(self) -> set[str]:
        return {IngestMode.NATIVE, IngestMode.IMPORT}  # owned-channel API + transcript files

    # ---- helpers ---------------------------------------------------------------

    @staticmethod
    def _token(account) -> str | None:
        return getattr(account, "access_token", None)

    def _uploads_playlist(self, account) -> str | None:
        """The 'uploads' playlist id holds every video the channel has published."""
        data = self._t.get("channels", {
            "part": "contentDetails", "id": account.external_account_id}, self._token(account))
        items = data.get("items") or []
        if not items:
            return None
        return (items[0].get("contentDetails", {})
                .get("relatedPlaylists", {}).get("uploads"))

    # page caps: a backstop against an unbounded cursor walk (≈2k items each)
    _MAX_CONTENT_PAGES = 40
    _MAX_COMMENT_PAGES = 20

    @staticmethod
    def _map_items(data: dict) -> list[NormalizedContent]:
        out: list[NormalizedContent] = []
        for it in data.get("items", []):
            sn = it.get("snippet", {})
            vid = (it.get("contentDetails", {}).get("videoId")
                   or sn.get("resourceId", {}).get("videoId"))
            if not vid:
                continue
            caption = "\n".join(filter(None, [sn.get("title"), sn.get("description")])) or None
            out.append(NormalizedContent(
                external_id=vid, kind="video", caption=caption,
                permalink=f"https://www.youtube.com/watch?v={vid}",
                posted_at=_parse_dt(sn.get("publishedAt")),
            ))
        return out

    @staticmethod
    def _map_threads(data: dict, content_external_id: str) -> list[NormalizedInteraction]:
        out: list[NormalizedInteraction] = []
        for it in data.get("items", []):
            top_wrap = it.get("snippet", {}).get("topLevelComment", {})
            top = top_wrap.get("snippet", {})
            text = top.get("textOriginal") or top.get("textDisplay")
            if not text:
                continue
            out.append(NormalizedInteraction(
                external_id=top_wrap.get("id") or it.get("id"),
                text=text,
                author_external_id=(top.get("authorChannelId") or {}).get("value", "unknown"),
                created_at=_parse_dt(top.get("publishedAt")),
                content_external_id=content_external_id, kind="comment",
            ))
        return out

    # ---- content ---------------------------------------------------------------

    def backfill_content(self, account) -> list[NormalizedContent]:
        """Walk the full uploads playlist (all pages), not just the newest 50."""
        uploads = self._uploads_playlist(account)
        if not uploads:
            return []
        out: list[NormalizedContent] = []
        cursor = None
        for _ in range(self._MAX_CONTENT_PAGES):
            items, cursor = self.sync_content(account, cursor, _uploads=uploads)
            out.extend(items)
            if not cursor:
                break
        return out

    def sync_content(self, account, cursor: str | None = None, *, _uploads: str | None = None):
        uploads = _uploads or self._uploads_playlist(account)
        if not uploads:
            return [], None
        params = {"part": "snippet,contentDetails", "playlistId": uploads, "maxResults": 50}
        if cursor:
            params["pageToken"] = cursor
        data = self._t.get("playlistItems", params, self._token(account))
        return self._map_items(data), data.get("nextPageToken")

    # ---- interactions ----------------------------------------------------------

    def backfill_interactions(self, account, content_external_id: str):
        """All comment pages for a video. Caller is expected to tolerate a raised
        error here (e.g. a 403 on a comments-disabled video); see sync_native."""
        out: list[NormalizedInteraction] = []
        cursor = None
        for _ in range(self._MAX_COMMENT_PAGES):
            params = {"part": "snippet", "videoId": content_external_id, "maxResults": 100}
            if cursor:
                params["pageToken"] = cursor
            data = self._t.get("commentThreads", params, self._token(account))
            out.extend(self._map_threads(data, content_external_id))
            cursor = data.get("nextPageToken")
            if not cursor:
                break
        return out

    # ---- actions ---------------------------------------------------------------

    def reply_to_interaction(self, account, interaction_external_id: str, message: str):
        require(self, COMMENTS_REPLY)
        return self._t.post("comments", {"part": "snippet"}, {
            "snippet": {"parentId": interaction_external_id, "textOriginal": message}},
            self._token(account))
