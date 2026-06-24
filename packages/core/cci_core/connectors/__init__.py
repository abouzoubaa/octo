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
from cci_core.connectors.instagram import InstagramConnector
from cci_core.connectors.tiktok import TikTokConnector
from cci_core.connectors.youtube import YouTubeConnector

_REGISTRY: dict[str, type[Connector]] = {}


def register(connector_cls: type[Connector]) -> type[Connector]:
    _REGISTRY[connector_cls.platform] = connector_cls
    return connector_cls


def get_connector(platform: str) -> Connector | None:
    cls = _REGISTRY.get(platform)
    return cls() if cls else None


def supported_platforms() -> list[str]:
    return sorted(_REGISTRY)


def capabilities_for(platform: str) -> set[str]:
    c = get_connector(platform)
    return c.capabilities() if c else set()


# register the built-in connectors
register(InstagramConnector)
register(YouTubeConnector)
register(TikTokConnector)

__all__ = [
    "Connector", "NormalizedContent", "NormalizedInteraction", "IngestMode",
    "CapabilityError", "supports", "require", "ALL_CAPABILITIES",
    "register", "get_connector", "supported_platforms", "capabilities_for",
]
