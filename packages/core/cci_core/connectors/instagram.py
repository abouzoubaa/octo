"""Instagram connector — the reference full-loop connector (most capabilities).

Native ingest is delegated to the existing InstagramClient (Graph API), mapped into
the platform-agnostic Normalized* objects so sync_native treats Instagram exactly
like YouTube. The client is injectable so the whole path runs in tests without httpx.
"""
from __future__ import annotations

from typing import Any

from cci_core.connectors.base import (
    ANALYTICS_READ,
    CAPTIONS_READ,
    COMMENTS_READ,
    COMMENTS_REPLY,
    CONTENT_PUBLISH,
    CONTENT_READ,
    DELETIONS_RECEIVE,
    EVENTS_WEBHOOK,
    MEDIA_READ,
    MESSAGES_SEND,
    Connector,
    IngestMode,
    NormalizedContent,
    NormalizedInteraction,
    require,
)

_KIND = {"VIDEO": "video", "IMAGE": "image", "CAROUSEL_ALBUM": "carousel"}


def _default_client_factory(token: str):
    from cci_core.instagram import InstagramClient

    return InstagramClient(access_token=token)


class InstagramConnector(Connector):
    platform = "instagram"

    # backstops against an unbounded cursor walk if the API misbehaves (mirrors the
    # YouTube connector's page caps); upserts dedupe by external_id regardless.
    _MAX_MEDIA = 5000
    _MAX_COMMENTS = 5000

    def __init__(self, client_factory: Any | None = None):
        self._make_client = client_factory or _default_client_factory

    def capabilities(self) -> set[str]:
        # the comparatively complete loop: content, comments, messaging, publish, webhooks
        return {
            CONTENT_READ, MEDIA_READ, CAPTIONS_READ, COMMENTS_READ, COMMENTS_REPLY,
            MESSAGES_SEND, CONTENT_PUBLISH, EVENTS_WEBHOOK, DELETIONS_RECEIVE,
            ANALYTICS_READ,
        }

    def ingest_modes(self) -> set[str]:
        return {IngestMode.NATIVE}

    # ---- helpers ---------------------------------------------------------------

    def _client(self, account):
        return self._make_client(getattr(account, "access_token", None))

    @staticmethod
    def _ts(value):
        if not value:
            return None
        from cci_core.instagram import InstagramClient

        try:
            return InstagramClient.parse_ts(value)
        except (ValueError, TypeError, AttributeError):  # tolerate non-string/garbage
            return None

    @classmethod
    def _map_media(cls, m: dict) -> NormalizedContent:
        return NormalizedContent(
            external_id=str(m["id"]),
            kind=_KIND.get(m.get("media_type", ""), "post"),
            caption=m.get("caption"),
            permalink=m.get("permalink"),
            media_url=m.get("media_url") or m.get("thumbnail_url"),
            posted_at=cls._ts(m.get("timestamp")),
        )

    @classmethod
    def _map_comment(cls, c: dict, content_external_id: str) -> NormalizedInteraction:
        return NormalizedInteraction(
            external_id=str(c["id"]),
            text=c.get("text") or "",
            author_external_id=str((c.get("from") or {}).get("id", "unknown")),
            created_at=cls._ts(c.get("timestamp")),
            content_external_id=content_external_id, kind="comment",
        )

    # ---- content ---------------------------------------------------------------

    def backfill_content(self, account) -> list[NormalizedContent]:
        client = self._client(account)
        out: list[NormalizedContent] = []
        for m in client.iter_media(account.external_account_id):
            out.append(self._map_media(m))
            if len(out) >= self._MAX_MEDIA:
                break
        return out

    def sync_content(self, account, cursor: str | None = None):
        page = self._client(account).media_page(account.external_account_id, after=cursor)
        return [self._map_media(m) for m in page.items], page.after

    # ---- interactions ----------------------------------------------------------

    def backfill_interactions(self, account, content_external_id: str):
        client = self._client(account)
        out: list[NormalizedInteraction] = []
        for c, _cursor in client.iter_comments(content_external_id):
            out.append(self._map_comment(c, content_external_id))
            if len(out) >= self._MAX_COMMENTS:
                break
        return out

    # ---- actions ---------------------------------------------------------------

    def reply_to_interaction(self, account, interaction_external_id: str, message: str):
        require(self, COMMENTS_REPLY)
        return self._client(account).reply_to_comment(interaction_external_id, message)
