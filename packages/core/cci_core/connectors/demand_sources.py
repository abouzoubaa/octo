"""Pure demand-source connectors (forwarding/capture mode): newsletter, podcast,
Discord, forwarded DMs.

These have no creator content to ingest — their value is DEMAND. They feed
ExternalSignal rows into Demand Radar so "what is asked everywhere?" is real, not
just on-platform. Fed by a Sift BCC/forward address or a bot, never scraping.
"""
from __future__ import annotations

from cci_core.connectors.base import DEMAND_READ, EVENTS_WEBHOOK, Connector, IngestMode


class _DemandSource(Connector):
    def capabilities(self) -> set[str]:
        return {DEMAND_READ, EVENTS_WEBHOOK}

    def ingest_modes(self) -> set[str]:
        return {IngestMode.FORWARD}


class NewsletterConnector(_DemandSource):
    platform = "newsletter"


class PodcastConnector(_DemandSource):
    platform = "podcast"


class DiscordConnector(_DemandSource):
    platform = "discord"
