"""Connector registry — resolve a Connector by platform name.

New platforms register here. Product logic asks the registry for a connector and
reads its capabilities(); it never imports a platform module directly.
"""
from __future__ import annotations

from cci_core.connectors.base import (
    ALL_CAPABILITIES,
    CapabilityError,
    Connector,
    IngestMode,
    NormalizedContent,
    NormalizedInteraction,
    require,
    supports,
)
from cci_core.connectors.demand_sources import (
    DiscordConnector,
    NewsletterConnector,
    PodcastConnector,
)
from cci_core.connectors.instagram import InstagramConnector
from cci_core.connectors.tiktok import TikTokConnector
from cci_core.connectors.youtube import YouTubeConnector

_REGISTRY: dict[str, type[Connector]] = {}


def register(connector_cls: type[Connector]) -> type[Connector]:
    _REGISTRY[connector_cls.platform] = connector_cls
    return connector_cls


def get_connector(platform: str, *, full_loop: bool = False) -> Connector | None:
    """Resolve a connector. `full_loop` is a per-account grant (e.g. a TikTok account
    approved for comments + messaging); it's forwarded to connectors that support
    capability tiers and ignored by the rest."""
    cls = _REGISTRY.get(platform)
    if cls is None:
        return None
    try:
        return cls(full_loop=full_loop)  # tiered connectors (TikTok) accept the grant
    except TypeError:
        return cls()  # the rest have a uniform capability set


def supported_platforms() -> list[str]:
    return sorted(_REGISTRY)


def capabilities_for(platform: str, *, full_loop: bool = False) -> set[str]:
    c = get_connector(platform, full_loop=full_loop)
    return c.capabilities() if c else set()


# register the built-in connectors
register(InstagramConnector)
register(YouTubeConnector)
register(TikTokConnector)
register(NewsletterConnector)
register(PodcastConnector)
register(DiscordConnector)

__all__ = [
    "Connector", "NormalizedContent", "NormalizedInteraction", "IngestMode",
    "CapabilityError", "supports", "require", "ALL_CAPABILITIES",
    "register", "get_connector", "supported_platforms", "capabilities_for",
]
