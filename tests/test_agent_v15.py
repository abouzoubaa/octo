"""v1.5 assist features: drafting, briefing, gap map, inbox, waitlist, monetization."""
from sqlalchemy import select

from cci_agent.briefing import build_briefing, content_gap_map, render_briefing_text
from cci_agent.drafting import creator_recall, generate_brief, generate_draft
from cci_agent.inbox import (
    add_to_waitlist,
    bounded_clarify,
    label_message,
    labelled_inbox,
    match_playbook,
)
from cci_agent.monetization import inject_affiliate, offer_cta, with_utm
from cci_core.models import ContentDraft, DemandTopic, Offer, Playbook, Post, WaitlistEntry
from cci_workers.radar import build_radar


def _radar(seeded_creator, session):
    build_radar(seeded_creator.id, backlog=True)
    session.expire_all()
    return session.scalars(
        select(DemandTopic).where(DemandTopic.creator_id == seeded_creator.id)
    ).all()


# ----------------------------------------------------------------- drafting


def test_generate_brief_has_sources_and_phrasing(seeded_creator, session):
    topic = _radar(seeded_creator, session)[0]
    brief = generate_brief(session, seeded_creator.id, topic)
    assert "sources" in brief
    assert isinstance(brief.get("audience_phrasing", []), list)


def test_generate_draft_persists_grounded_draft(seeded_creator, session):
    topic = _radar(seeded_creator, session)[0]
    draft = generate_draft(session, seeded_creator.id, topic, persist=True)
    assert draft.id and draft.status == "draft"
    assert draft.demand_topic_id == topic.id
    stored = session.get(ContentDraft, draft.id)
    assert stored is not None


def test_creator_recall_returns_own_sentences(seeded_creator, session):
    hits = creator_recall(session, seeded_creator.id, "how to handle price objections")
    assert hits
    assert hits[0]["permalink"]
    assert "sentence" in hits[0]


# ------------------------------------------------------------- briefing + gap map


def test_build_briefing_assembles_sections(seeded_creator, session):
    _radar(seeded_creator, session)
    briefing = build_briefing(session, seeded_creator.id, with_draft=True)
    assert briefing is not None
    assert briefing["top_demand"]
    assert "drafted_post" in briefing
    text = render_briefing_text(briefing)
    assert "Briefing" in text and seeded_creator.handle in text


def test_gap_map_classifies_coverage(seeded_creator, session):
    _radar(seeded_creator, session)
    gm = content_gap_map(session, seeded_creator.id)
    assert gm
    assert all(g["coverage"] in ("well", "partial", "gap") for g in gm)


def test_briefing_none_without_signal(creator, session):
    assert build_briefing(session, creator.id) is None


# --------------------------------------------------------------------- inbox


def test_label_message_buckets():
    assert label_message("how much is your course?") == "purchase_intent"
    assert label_message("want to collab with our brand") == "collab_lead"
    assert label_message("where's the post about meal prep?") == "content_request"


def test_labelled_inbox_prioritised(seeded_creator, session):
    items = labelled_inbox(session, seeded_creator.id)
    assert items
    priorities = [i["priority"] for i in items]
    assert priorities == sorted(priorities)  # purchase intent floats to the top


def test_match_playbook(seeded_creator, session):
    session.add(Playbook(creator_id=seeded_creator.id, name="Pricing",
                         trigger_keywords=["price", "cost"], dm_template="Here's pricing…"))
    session.flush()
    pb = match_playbook(session, seeded_creator.id, "what's the price?")
    assert pb is not None and pb.name == "Pricing"
    assert match_playbook(session, seeded_creator.id, "nice post!") is None


def test_waitlist_capture(seeded_creator, session):
    add_to_waitlist(session, seeded_creator.id, "fan@example.com", "carb cycling")
    entry = session.scalar(select(WaitlistEntry).where(
        WaitlistEntry.creator_id == seeded_creator.id))
    assert entry.email == "fan@example.com"
    assert entry.notified is False


def test_bounded_clarify_shape(seeded_creator, session):
    # fake LLM returns a generic JSON; bounded_clarify tolerates missing options
    result = bounded_clarify("workout")
    assert result is None or set(result.keys()) == {"question", "options"}


# --------------------------------------------------------------- monetization


def test_with_utm_appends_params():
    url = with_utm("https://example.com/buy?ref=x")
    assert "utm_source=sift" in url and "ref=x" in url


def test_inject_affiliate_appends_only_mapped_products(seeded_creator, session):
    from cci_core.models import Product, ProductLink

    post = session.scalar(select(Post).where(Post.creator_id == seeded_creator.id))
    product = session.scalar(select(Product).where(Product.creator_id == seeded_creator.id))
    session.add(ProductLink(post_id=post.id, product_id=product.id))
    session.flush()
    out = inject_affiliate(session, post.id, "Great workout today")
    assert product.name in out and "utm_source=sift" in out


def test_offer_cta_routes_to_matching_offer(seeded_creator, session):
    session.add(Offer(creator_id=seeded_creator.id, name="Protein guide", kind="product",
                      url="https://example.com/guide", topics=["protein", "breakfast"],
                      priority=2, active=True))
    session.flush()
    cta = offer_cta(session, seeded_creator.id, ["breakfast"])
    assert cta is not None and cta["name"] == "Protein guide"
    assert "utm_source=sift" in cta["url"]
