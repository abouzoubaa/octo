"""YouTube Data API client — owned/authorized channels only.

Caption download requires permission to edit the video, so this path is only
for the creator's own channel (plan §"data reality"). For owned channels we
pull the uploads playlist and captions via OAuth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

import httpx

BASE = "https://www.googleapis.com/youtube/v3"


@dataclass
class YouTubeClient:
    api_key: str = ""
    oauth_token: str | None = None  # required for caption download
    _client: httpx.Client = field(default=None, repr=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._client = httpx.Client(timeout=30)

    def _get(self, path: str, **params) -> dict[str, Any]:
        headers = {}
        if self.oauth_token:
            headers["Authorization"] = f"Bearer {self.oauth_token}"
        else:
            params["key"] = self.api_key
        resp = self._client.get(f"{BASE}/{path}", params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def uploads_playlist_id(self, channel_id: str) -> str:
        data = self._get("channels", part="contentDetails", id=channel_id)
        return data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def iter_videos(self, channel_id: str) -> Iterator[dict[str, Any]]:
        playlist = self.uploads_playlist_id(channel_id)
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "part": "snippet,contentDetails",
                "playlistId": playlist,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._get("playlistItems", **params)
            yield from data.get("items", [])
            page_token = data.get("nextPageToken")
            if not page_token:
                return

    def list_captions(self, video_id: str) -> list[dict[str, Any]]:
        return self._get("captions", part="snippet", videoId=video_id).get("items", [])

    def download_caption(self, caption_id: str) -> str:
        """Requires OAuth with edit permission on the video (owned channel only)."""
        if not self.oauth_token:
            raise PermissionError("Caption download requires an OAuth token for the channel owner")
        resp = self._client.get(
            f"{BASE}/captions/{caption_id}",
            params={"tfmt": "srt"},
            headers={"Authorization": f"Bearer {self.oauth_token}"},
        )
        resp.raise_for_status()
        return resp.text
