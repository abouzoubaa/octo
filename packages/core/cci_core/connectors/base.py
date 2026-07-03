"""The Sift Connector Framework — one contract above every platform.

Product logic never talks to a platform directly: it talks to a Connector. Each
connector declares its CAPABILITIES (a TikTok account may have content+publish but
not comments; a podcast feed may have only content), and the UI/agent adapt to what
is actually available rather than pretending every account supports the same loop.

Three ingestion modes are first-class (none of them scraping):
- native API   (OAuth + webhooks + incremental sync)
- creator imports (export ZIP, uploaded media, transcript files)
- forwarding/capture (newsletter BCC, bot events, RSS)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

# ---- capability registry -------------------------------------------------------

CONTENT_READ = "content.read"
MEDIA_READ = "media.read"
CAPTIONS_READ = "captions.read"
COMMENTS_READ = "comments.read"
MESSAGES_READ = "messages.read"
DEMAND_READ = "demand.read"  # pure demand source (newsletter replies, forwarded asks)
ANALYTICS_READ = "analytics.read"
EVENTS_WEBHOOK = "events.webhook"
COMMENTS_REPLY = "comments.reply"
MESSAGES_SEND = "messages.send"
CONTENT_PUBLISH = "content.publish"
DELETIONS_RECEIVE = "deletions.receive"

ALL_CAPABILITIES = (
    CONTENT_READ, MEDIA_READ, CAPTIONS_READ, COMMENTS_READ, MESSAGES_READ, DEMAND_READ,
    ANALYTICS_READ, EVENTS_WEBHOOK, COMMENTS_REPLY, MESSAGES_SEND, CONTENT_PUBLISH,
    DELETIONS_RECEIVE,
)


class IngestMode:
    NATIVE = "native"      # OAuth + API + webhooks
    IMPORT = "import"      # creator-supplied export/upload
    FORWARD = "forward"    # BCC / bot events / RSS


# ---- normalised objects the connector yields (mapped into Sift models) ---------


@dataclass
class NormalizedContent:
    """One piece of creator content, platform-agnostic."""

    external_id: str
    kind: str  # video | image | carousel | short | post
    caption: str | None = None
    permalink: str | None = None
    posted_at: datetime | None = None
    media_url: str | None = None
    transcript: str | None = None
    transcript_segments: list | None = None
    impressions: int | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class NormalizedInteraction:
    """One audience interaction (comment / message / reply)."""

    external_id: str
    text: str
    author_external_id: str  # pseudonymised by Sift, never stored raw
    created_at: datetime | None = None
    content_external_id: str | None = None  # which content it's on
    kind: str = "comment"  # comment | message | story_reply


# ---- the connector contract ----------------------------------------------------


class Connector(ABC):
    """Every platform implements this. Methods an account can't do are simply not
    advertised in capabilities() and should not be called (the framework checks)."""

    platform: str = "base"

    @abstractmethod
    def capabilities(self) -> set[str]:
        """What this connected account actually supports (subset of ALL_CAPABILITIES)."""

    def ingest_modes(self) -> set[str]:
        return {IngestMode.NATIVE}

    # content
    def backfill_content(self, account) -> list[NormalizedContent]:  # noqa: ARG002
        return []

    def sync_content(self, account, cursor: str | None = None):  # noqa: ARG002
        return [], None  # (items, next_cursor)

    # interactions
    def backfill_interactions(self, account, content_external_id: str):  # noqa: ARG002
        return []

    # actions (only if advertised)
    def reply_to_interaction(self, account, interaction_external_id: str, message: str):
        raise NotImplementedError

    def publish_content(self, account, draft) -> dict:  # noqa: ARG002
        raise NotImplementedError

    def refresh_authorization(self, account) -> None:  # noqa: ARG002
        return None


def supports(connector: Connector, capability: str) -> bool:
    return capability in connector.capabilities()


def require(connector: Connector, capability: str) -> None:
    if not supports(connector, capability):
        raise CapabilityError(
            f"{connector.platform} account lacks '{capability}'")


class CapabilityError(Exception):
    """Raised when an action is attempted that the account doesn't support."""
