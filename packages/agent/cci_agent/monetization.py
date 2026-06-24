"""Monetization (v1.5): auto-affiliate injection + offer-aware CTAs.

Every question is declared intent. These attach the right product/offer link —
the creator-approved one — to captions, answers, and recommendations automatically.
"""
from __future__ import annotations

from urllib.parse import urlencode, urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.agent_foundations import select_offer
from cci_core.models import Product, ProductLink

# Visible disclosures — monetized links must never masquerade as neutral results.
AFFILIATE_DISCLOSURE = "Affiliate link — the creator may earn a commission."
OFFER_DISCLOSURE = "The creator's own paid offer."


def with_utm(url: str, *, source: str = "sift", medium: str = "auto", campaign: str = "caption") -> str:
    """Append UTM params for attribution without clobbering existing query."""
    parts = urlparse(url)
    existing = parts.query
    utm = urlencode({"utm_source": source, "utm_medium": medium, "utm_campaign": campaign})
    query = f"{existing}&{utm}" if existing else utm
    return urlunparse(parts._replace(query=query))


def inject_affiliate(session: Session, post_id: str, caption: str) -> str:
    """At caption time, append the approved affiliate link(s) for products mapped
    to this post (with UTM) — WITH a visible affiliate disclosure. Only
    creator-approved products are ever appended."""
    products = session.scalars(
        select(Product).join(ProductLink, ProductLink.product_id == Product.id)
        .where(ProductLink.post_id == post_id, Product.approved.is_(True),
               Product.affiliate_url.isnot(None))
    ).all()
    if not products:
        return caption
    links = [f"{p.name}: {with_utm(p.affiliate_url)}" for p in products]
    return f"{caption}\n\n—\n{AFFILIATE_DISCLOSURE}\n" + "\n".join(links)


def offer_cta(session: Session, creator_id: str, topics: list[str]) -> dict | None:
    """The right current offer for an answer/recommendation — WITH the reason it was
    selected and a visible disclosure (trust firewall: never disguise a paid CTA)."""
    offer, reason = select_offer(session, creator_id, topics)
    if offer is None:
        return None
    url = with_utm(offer.url, campaign="answer_cta") if offer.url else None
    is_affiliate = offer.kind == "product" and offer.product_id is not None
    return {
        "offer_id": offer.id, "name": offer.name, "kind": offer.kind, "url": url,
        "selected_because": reason,  # auditable: topic_match | priority_fallback
        "disclosure": AFFILIATE_DISCLOSURE if is_affiliate else OFFER_DISCLOSURE,
        "is_paid": True,
    }
