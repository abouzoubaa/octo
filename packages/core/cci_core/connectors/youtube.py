"""YouTube connector — best deep, citable source material; strong comments.

Caption download requires creator authorization for the channel, which fits Sift's
creator-connected model.
"""
from __future__ import annotations

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
)


class YouTubeConnector(Connector):
    platform = "youtube"

    def capabilities(self) -> set[str]:
        # comments + creator-authorized captions + analytics + upload notifications.
        # No private messaging surface like IG DMs.
        return {
            CONTENT_READ, MEDIA_READ, CAPTIONS_READ, COMMENTS_READ, COMMENTS_REPLY,
            CONTENT_PUBLISH, EVENTS_WEBHOOK, ANALYTICS_READ,
        }

    def ingest_modes(self) -> set[str]:
        return {IngestMode.NATIVE, IngestMode.IMPORT}  # owned-channel API + transcript files
