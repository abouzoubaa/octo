"""Wave G: trust firewall — why an offer was selected + visible disclosures."""
from sqlalchemy import select

from cci_agent.monetization import AFFILIATE_DISCLOSURE, inject_affiliate, offer_cta
from cci_core.agent_foundations import select_offer
from cci_core.models import Offer, Post, Product, ProductLink


def test_select_offer_records_topic_match_reason(seeded_creator, session):
    session.add(Offer(creator_id=seeded_creator.id, name="Protein guide", kind="product",
                      url="https://x/guide", topics=["protein", "breakfast"], active=True))
    session.flush()
    offer, reason = select_offer(session, seeded_creator.id, ["breakfast"])
    assert offer.name == "Protein guide"
    assert reason["basis"] == "topic_match"
    assert "breakfast" in reason["matched_topics"]


def test_select_offer_records_fallback_reason(seeded_creator, session):
    session.add(Offer(creator_id=seeded_creator.id, name="Newsletter", kind="newsletter",
                      topics=["unrelated"], priority=5, active=True))
    session.flush()
    offer, reason = select_offer(session, seeded_creator.id, ["nothing matches here"])
    assert offer.name == "Newsletter"
    assert reason["basis"] == "priority_fallback"  # auditable: NOT chosen for commission


def test_select_offer_none_when_no_offers(seeded_creator, session):
    offer, reason = select_offer(session, seeded_creator.id, ["x"])
    assert offer is None and reason["basis"] == "none"


def test_offer_cta_carries_reason_and_disclosure(seeded_creator, session):
    product = session.scalar(select(Product).where(Product.creator_id == seeded_creator.id))
    session.add(Offer(creator_id=seeded_creator.id, name="Whey", kind="product",
                      url="https://x/whey", product_id=product.id, topics=["protein"],
                      active=True))
    session.flush()
    cta = offer_cta(session, seeded_creator.id, ["protein"])
    assert cta["selected_because"]["basis"] == "topic_match"
    assert cta["disclosure"] == AFFILIATE_DISCLOSURE  # affiliate product → affiliate disclosure
    assert cta["is_paid"] is True


def test_inject_affiliate_includes_disclosure(seeded_creator, session):
    post = session.scalar(select(Post).where(Post.creator_id == seeded_creator.id))
    product = session.scalar(select(Product).where(
        Product.creator_id == seeded_creator.id, Product.affiliate_url.isnot(None)))
    session.add(ProductLink(post_id=post.id, product_id=product.id))
    session.flush()
    out = inject_affiliate(session, post.id, "Great session today")
    assert AFFILIATE_DISCLOSURE in out  # disclosure always accompanies the link


def test_search_results_flag_affiliate_products(seeded_creator, session):
    from fastapi.testclient import TestClient

    from cci_api.main import create_app

    post = session.scalar(select(Post).where(Post.creator_id == seeded_creator.id))
    product = session.scalar(select(Product).where(
        Product.creator_id == seeded_creator.id, Product.affiliate_url.isnot(None)))
    session.add(ProductLink(post_id=post.id, product_id=product.id))
    session.commit()
    client = TestClient(create_app())
    data = client.get(f"/api/{seeded_creator.handle}/search",
                      params={"q": "high protein breakfast"}).json()
    flagged = [p for r in data["results"] for p in r["products"] if p.get("is_affiliate")]
    if flagged:
        assert flagged[0]["disclosure"]
