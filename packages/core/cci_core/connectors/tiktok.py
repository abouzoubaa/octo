"""TikTok connector — Sift's strongest market-facing wedge, but comment/message
access is conditional. So TikTok ships at TWO capability levels and the registry/UI
shows which is active rather than pretending every account has the full loop:

- Archive  (default): content + captions(transcribed) + search + citations + Demand
  Radar from imported/accessible interactions. No dependency on comment access.
- Full loop (where approved): comments, business messages, replies, publishing.

We never scrape — Archive mode is fed by the Content Posting/Display APIs for owned
accounts or by creator-supplied video import.
"""
from __future__ import annotations

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
)

# what an Archive-level TikTok account supports
ARCHIVE_CAPS = {CONTENT_READ, MEDIA_READ, CAPTIONS_READ, CONTENT_PUBLISH}
# additional capabilities a Full-loop (approved) account unlocks
FULL_LOOP_CAPS = ARCHIVE_CAPS | {COMMENTS_READ, COMMENTS_REPLY, MESSAGES_SEND}


class TikTokConnector(Connector):
    platform = "tiktok"

    def __init__(self, full_loop: bool = False):
        self.full_loop = full_loop

    def capabilities(self) -> set[str]:
        return set(FULL_LOOP_CAPS if self.full_loop else ARCHIVE_CAPS)

    def ingest_modes(self) -> set[str]:
        # owned-account API where available, plus creator video import (the MVP path)
        return {IngestMode.NATIVE, IngestMode.IMPORT}
