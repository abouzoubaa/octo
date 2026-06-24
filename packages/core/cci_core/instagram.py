"""Instagram API client (Instagram Login flavour — no Facebook Page required).

Compliance constraints encoded here (plan §4.1, §4.5):
- Official API only; never scrape.
- Comment reads are cursor-paginated (~50/page, no timestamp filter): we walk
  cursors and the caller persists a per-post watermark for incremental sync.
- Private replies: exactly one message per comment, within seven days.
- API calls are budgeted per account → callers batch; we keep a polite delay knob.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator

import httpx

from cci_core.config import get_settings

MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,media_url,thumbnail_url,"
    "permalink,timestamp,children{id,media_type,media_url}"
)
COMMENT_FIELDS = "id,text,timestamp,from,replies{id,text,timestamp,from}"


@dataclass
class IgPage:
    """One page of a cursor-paginated listing."""

    items: list[dict[str, Any]]
    after: str | None  # cursor to resume from (the caller's watermark)


@dataclass
class InstagramClient:
    access_token: str
    base_url: str = ""
    request_delay_s: float = 0.0  # politeness knob for backfills
    _client: httpx.Client = field(default=None, repr=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.base_url = self.base_url or get_settings().ig_graph_base
        self._client = httpx.Client(timeout=30)

    # ------------------------------------------------------------------ internals

    def _get(self, path: str, **params) -> dict[str, Any]:
        params["access_token"] = self.access_token
        if self.request_delay_s:
            time.sleep(self.request_delay_s)
        resp = self._client.get(f"{self.base_url}/{path.lstrip('/')}", params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, **data) -> dict[str, Any]:
        data["access_token"] = self.access_token
        resp = self._client.post(f"{self.base_url}/{path.lstrip('/')}", data=data)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _cursor(payload: dict[str, Any]) -> str | None:
        return payload.get("paging", {}).get("cursors", {}).get("after")

    # ------------------------------------------------------------------- profile

    def me(self) -> dict[str, Any]:
        return self._get("me", fields="id,username,account_type,media_count")

    # --------------------------------------------------------------------- media

    def media_page(self, ig_user_id: str, after: str | None = None, limit: int = 50) -> IgPage:
        params: dict[str, Any] = {"fields": MEDIA_FIELDS, "limit": limit}
        if after:
            params["after"] = after
        payload = self._get(f"{ig_user_id}/media", **params)
        return IgPage(items=payload.get("data", []), after=self._cursor(payload))

    def iter_media(self, ig_user_id: str, after: str | None = None) -> Iterator[dict[str, Any]]:
        """Walk the full media history from an optional resume cursor."""
        while True:
            page = self.media_page(ig_user_id, after=after)
            yield from page.items
            if not page.after or not page.items:
                return
            after = page.after

    # ------------------------------------------------------------------ comments

    def comments_page(self, media_id: str, after: str | None = None, limit: int = 50) -> IgPage:
        params: dict[str, Any] = {"fields": COMMENT_FIELDS, "limit": limit}
        if after:
            params["after"] = after
        payload = self._get(f"{media_id}/comments", **params)
        return IgPage(items=payload.get("data", []), after=self._cursor(payload))

    def iter_comments(self, media_id: str, after: str | None = None) -> Iterator[tuple[dict, str | None]]:
        """Yield (comment, page_cursor) so the caller can persist a watermark per page."""
        while True:
            page = self.comments_page(media_id, after=after)
            for item in page.items:
                yield item, page.after
            if not page.after or not page.items:
                return
            after = page.after

    # ------------------------------------------------------------ replies & DMs

    def reply_to_comment(self, comment_id: str, message: str) -> dict[str, Any]:
        """Public threaded reply under the comment."""
        return self._post(f"{comment_id}/replies", message=message)

    def private_reply(self, comment_id: str, message: str) -> dict[str, Any]:
        """Private reply to a comment author.

        Platform rule: ONE message per comment, within 7 days; follow-ups only if
        the person replies. Enforced upstream by DmJob (unique per comment) and the
        dispatcher's window check — this is just the transport.
        """
        return self._post(
            "me/messages",
            recipient=f'{{"comment_id":"{comment_id}"}}',
            message=f'{{"text":{_json_str(message)}}}',
        )

    @staticmethod
    def parse_ts(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("+0000", "+00:00"))


def _json_str(text: str) -> str:
    import json

    return json.dumps(text)


def exchange_code_for_token(code: str, redirect_uri: str) -> dict[str, Any]:
    """OAuth code → short-lived token (Instagram Login)."""
    s = get_settings()
    resp = httpx.post(
        "https://api.instagram.com/oauth/access_token",
        data={
            "client_id": s.ig_app_id,
            "client_secret": s.ig_app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def exchange_for_long_lived(short_token: str) -> dict[str, Any]:
    s = get_settings()
    resp = httpx.get(
        f"{s.ig_graph_base}/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": s.ig_app_secret,
            "access_token": short_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# Scopes requested at OAuth time — only what the product visibly uses (extra
# scopes are a common App Review rejection reason).
IG_SCOPES = (
    "instagram_business_basic,instagram_business_manage_comments,"
    "instagram_business_manage_messages"
)


def authorize_url(redirect_uri: str, state: str) -> str:
    """The Instagram Login consent URL to send a connecting creator to."""
    from urllib.parse import urlencode

    s = get_settings()
    params = urlencode({
        "client_id": s.ig_app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": IG_SCOPES,
        "state": state,
    })
    return f"https://www.instagram.com/oauth/authorize?{params}"


def refresh_long_lived(long_token: str) -> dict[str, Any]:
    """Refresh a long-lived token (valid ~60 days) before it expires."""
    s = get_settings()
    resp = httpx.get(
        f"{s.ig_graph_base}/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": long_token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
