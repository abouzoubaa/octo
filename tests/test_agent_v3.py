"""v3 scale features: performance, planning, pricing, CRM, team, growth, public API."""
from sqlalchemy import select

from cci_agent.crm import customer_profiles, lifecycle_segments
from cci_agent.growth import (
    competitor_radar,
    export_task,
    peer_benchmark,
    plagiarism_scan,
)
from cci_agent.scale import (
    content_calendar,
    education_plan,
    predict_performance,
    pricing_insights,
    revenue_forecast,
    thumbnail_concepts,
)
from cci_agent.team import (
    add_member,
    has_capability,
    mint_api_key,
    revoke_api_key,
    verify_api_key,
)
from cci_core.agent_foundations import get_rules
from cci_core.models import Comment, ContentDraft, DemandTopic, Post, TeamRole
from cci_workers.radar import build_radar


def _radar(seeded_creator, session):
    build_radar(seeded_creator.id, backlog=True)
    session.expire_all()
    return session.scalars(
        select(DemandTopic).where(DemandTopic.creator_id == seeded_creator.id)).all()


# ----------------------------------------------------------------- scale


def test_predict_performance_needs_history(creator, session):
    draft = ContentDraft(creator_id=creator.id, title="x", hooks=["hi"], script="short")
    session.add(draft)
    session.flush()
    assert predict_performance(session, creator.id, draft)["score"] is None


def test_predict_performance_scores_with_corpus(seeded_creator, session):
    topic = _radar(seeded_creator, session)[0]
    draft = ContentDraft(creator_id=seeded_creator.id, title="x", demand_topic_id=topic.id,
                         hooks=["What can I eat?"], script="A grounded short script here.")
    session.add(draft)
    session.flush()
    result = predict_performance(session, seeded_creator.id, draft)
    assert isinstance(result["score"], int) and 0 <= result["score"] <= 100


def test_content_calendar(seeded_creator, session):
    _radar(seeded_creator, session)
    cal = content_calendar(session, seeded_creator.id)
    assert "cadence_days" in cal and "queue" in cal


def test_pricing_insights(seeded_creator, session):
    session.add(Comment(creator_id=seeded_creator.id, external_id="pq", author_pseudonym="a",
                        text="how much does your course cost?", is_question=True))
    session.flush()
    out = pricing_insights(session, seeded_creator.id)
    assert out["price_questions"] >= 1 and out["insight"]


def test_revenue_forecast_shape(seeded_creator, session):
    out = revenue_forecast(session, seeded_creator.id)
    assert "trend" in out and "affiliate_clicks" in out


def test_education_plan(seeded_creator, session):
    plan = education_plan(session, seeded_creator.id)
    assert "based_on" in plan


def test_thumbnail_concepts(seeded_creator, session):
    out = thumbnail_concepts(session, seeded_creator.id, "3 no-egg breakfasts")
    assert "concepts" in out


# ----------------------------------------------------------------- CRM


def test_customer_profiles_and_lifecycle(seeded_creator, session):
    profiles = customer_profiles(session, seeded_creator.id)
    assert isinstance(profiles, list)
    segments = lifecycle_segments(session, seeded_creator.id)
    assert {"engaged", "dormant", "new", "waitlist_leads"} <= set(segments.keys())


# ----------------------------------------------------------------- team & roles


def test_roles_capabilities(seeded_creator, session):
    add_member(session, seeded_creator.id, "va@example.com", TeamRole.analytics)
    add_member(session, seeded_creator.id, "writer@example.com", TeamRole.contractor)
    assert has_capability(session, seeded_creator.id, "va@example.com", "read")
    assert not has_capability(session, seeded_creator.id, "va@example.com", "publish")
    assert has_capability(session, seeded_creator.id, "writer@example.com", "draft")
    assert not has_capability(session, seeded_creator.id, "writer@example.com", "approve")


def test_api_key_lifecycle(seeded_creator, session):
    record, full = mint_api_key(session, seeded_creator.id, "ci", scopes=["demand:read"])
    assert full.startswith("sift_")
    assert verify_api_key(session, full).id == record.id
    assert verify_api_key(session, "sift_bogus_key") is None
    revoke_api_key(session, record.id)
    assert verify_api_key(session, full) is None  # revoked keys rejected


# ----------------------------------------------------------------- growth (opt-in)


def test_benchmark_opt_in_gate(seeded_creator, session):
    assert peer_benchmark(session, seeded_creator.id)["enabled"] is False
    rules = get_rules(session, seeded_creator.id)
    rules.allow_benchmarking = True
    session.flush()
    out = peer_benchmark(session, seeded_creator.id)
    assert out["enabled"] is True and "you" in out


def test_competitor_radar_opt_in_gate(seeded_creator, session):
    assert competitor_radar(session, seeded_creator.id)["enabled"] is False


def test_plagiarism_scan_detects_own_content(seeded_creator, session):
    _radar(seeded_creator, session)  # ensures corpus indexed
    post = session.scalar(select(Post).where(Post.creator_id == seeded_creator.id,
                                             Post.caption.isnot(None)))
    out = plagiarism_scan(session, seeded_creator.id, post.caption)
    assert out["match"] is True and out["similarity"] >= 0.82


def test_plagiarism_scan_unrelated_text(seeded_creator, session):
    out = plagiarism_scan(session, seeded_creator.id, "quarterly tax filing deadlines in France")
    assert "similarity" in out


def test_export_task_payload(seeded_creator, session):
    topic = _radar(seeded_creator, session)[0]
    out = export_task(session, seeded_creator.id, topic)
    assert out["exported"] is True
    assert out["task"]["demand_topic_id"] == topic.id
