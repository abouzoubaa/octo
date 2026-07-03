"""Locks the deferred cross-cutting review items: per-account TikTok capability
(covered in test_tiktok_connector), DM lock (test_review_hardening), and here:
agent-LLM cost metering + the anonymous-answer abuse ceiling + the pseudonym secret."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cci_api.main import create_app
from cci_core.config import get_settings
from cci_core.models import DemandTopic


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


def _topic(creator_id, session):
    from cci_workers.radar import build_radar

    build_radar(creator_id, backlog=True)
    session.expire_all()
    return session.scalar(select(DemandTopic).where(DemandTopic.creator_id == creator_id))


# ----------------------------------------------------- agent LLM cost metering


def test_draft_generation_meters_cost(seeded_creator, session):
    from cci_agent.drafting import generate_draft
    from cci_core.cost import monthly_cost_cents

    topic = _topic(seeded_creator.id, session)
    before = monthly_cost_cents(session, seeded_creator.id, op="draft")
    generate_draft(session, seeded_creator.id, topic, persist=False)
    after = monthly_cost_cents(session, seeded_creator.id, op="draft")
    assert after > before  # the agent generation now counts toward the cost cap


def test_monthly_cost_op_filter_isolates_ops(seeded_creator, session):
    from cci_core.cost import meter_llm, monthly_cost_cents

    meter_llm(session, seeded_creator.id, "x" * 4000, op="series")
    session.flush()
    assert monthly_cost_cents(session, seeded_creator.id, op="series") > 0
    assert monthly_cost_cents(session, seeded_creator.id, op="draft") == 0  # op-scoped


# ----------------------------------------------------- anonymous-answer abuse ceiling


def test_anon_answer_degrades_to_search_over_ceiling(client, seeded_creator, session, monkeypatch):
    from cci_core.cost import meter_llm

    # a tiny ceiling + any prior answer-op spend → the free anonymous answer card
    # degrades to plain search instead of letting a fan page drive unbounded LLM cost.
    monkeypatch.setattr(get_settings(), "anon_answer_monthly_cap_cents", 0.01)
    meter_llm(session, seeded_creator.id, "x" * 2000, op="answer")
    session.commit()

    data = client.get(f"/api/{seeded_creator.handle}/search",
                      params={"q": "how to handle price objections"}).json()
    assert data["answer"] is None  # LLM call skipped
    assert data["results"]  # plain search still serves


def test_anon_answer_present_under_ceiling(client, seeded_creator):
    # default $20 ceiling, no prior spend → the answer card works normally
    data = client.get(f"/api/{seeded_creator.handle}/search",
                      params={"q": "how to handle price objections"}).json()
    assert data["answer"] is not None


# ----------------------------------------------------- pseudonym secret


def test_pseudonym_uses_dedicated_secret_with_fallback(monkeypatch):
    from cci_core import privacy
    from cci_core.config import get_settings as gs

    # fallback: with no pseudonym_secret, keying is stable (admin_token)
    base = privacy.pseudonymize("fan-123", "creator-1")
    assert base == privacy.pseudonymize("fan-123", "creator-1")  # stable

    # a dedicated secret changes the pseudonym (decoupled from admin_token)
    monkeypatch.setattr(gs(), "pseudonym_secret", "a-dedicated-high-entropy-secret")
    assert privacy.pseudonymize("fan-123", "creator-1") != base
