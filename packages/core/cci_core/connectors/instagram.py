"""Instagram connector — the reference full-loop connector (most capabilities)."""
from __future__ import annotations

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
)


class InstagramConnector(Connector):
    platform = "instagram"

    def capabilities(self) -> set[str]:
        # the comparatively complete loop: content, comments, messaging, publish, webhooks
        return {
            CONTENT_READ, MEDIA_READ, CAPTIONS_READ, COMMENTS_READ, COMMENTS_REPLY,
            MESSAGES_SEND, CONTENT_PUBLISH, EVENTS_WEBHOOK, DELETIONS_RECEIVE,
            ANALYTICS_READ,
        }

    def ingest_modes(self) -> set[str]:
        return {IngestMode.NATIVE}
