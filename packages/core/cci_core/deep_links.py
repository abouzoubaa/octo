"""Deep links — every result and answer has a stable, shareable URL.

The DM sends the same URL a fan could share: it opens the creator's page with
the answer already loaded. Format: {base}/{creator_handle}?q=<query>&a=<answer_id>
"""
from urllib.parse import quote

from cci_core.config import get_settings


def search_link(creator_handle: str, query: str | None = None) -> str:
    base = get_settings().public_base_url.rstrip("/")
    url = f"{base}/{quote(creator_handle)}"
    if query:
        url += f"?q={quote(query)}"
    return url


def answer_link(creator_handle: str, query: str, answer_id: str) -> str:
    return f"{search_link(creator_handle, query)}&a={quote(answer_id)}"


def post_link(creator_handle: str, post_id: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/{quote(creator_handle)}/p/{quote(post_id)}"
