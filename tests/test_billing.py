"""Billing: plan gating, quotas, checkout, webhook, and API enforcement."""
import pytest
from fastapi.testclient import TestClient

from cci_api.main import create_app
from cci_core.billing import (
    PlanError,
    apply_subscription_event,
    assert_feature,
    check_quota,
    get_billing_provider,
    has_feature,
    plan_for,
)
from cci_core.config import get_settings
from cci_core.models import Plan


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


def _admin():
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


# ----------------------------------------------------------------- gating


def test_default_plan_is_free(seeded_creator, session):
    assert plan_for(session, seeded_creator.id) == Plan.free


def test_feature_gating_by_plan(seeded_creator, session):
    # free: no creator/pro features
    assert not has_feature(session, seeded_creator.id, "radar")
    assert not has_feature(session, seeded_creator.id, "draft_generator")

    apply_subscription_event(session, seeded_creator.id, plan=Plan.creator)
    assert has_feature(session, seeded_creator.id, "radar")  # creator tier
    assert not has_feature(session, seeded_creator.id, "draft_generator")  # still pro-only

    apply_subscription_event(session, seeded_creator.id, plan=Plan.pro)
    assert has_feature(session, seeded_creator.id, "draft_generator")  # pro inherits all


def test_assert_feature_raises(seeded_creator, session):
    with pytest.raises(PlanError) as ei:
        assert_feature(session, seeded_creator.id, "sponsor_reports")
    assert ei.value.code == "upgrade_required"


# ----------------------------------------------------------------- quotas


def test_quota_enforced_for_creator_plan(seeded_creator, session):
    from cci_core import events

    apply_subscription_event(session, seeded_creator.id, plan=Plan.creator)
    session.flush()
    # creator plan allows 20 drafts/month — simulate hitting the cap
    for _ in range(20):
        events.track(session, "drafts", seeded_creator.id)
    session.flush()
    with pytest.raises(PlanError) as ei:
        check_quota(session, seeded_creator.id, "drafts")
    assert ei.value.code == "quota_exceeded"


def test_pro_plan_unlimited(seeded_creator, session):
    from cci_core import events

    apply_subscription_event(session, seeded_creator.id, plan=Plan.pro)
    for _ in range(50):
        events.track(session, "drafts", seeded_creator.id)
    session.flush()
    check_quota(session, seeded_creator.id, "drafts")  # no raise — unlimited


# ----------------------------------------------------------------- provider


def test_fake_checkout_and_webhook_roundtrip(seeded_creator, session):
    import json

    provider = get_billing_provider()
    url = provider.create_checkout(seeded_creator.id, Plan.pro, "http://x/studio")
    assert "plan=pro" in url
    raw = json.dumps({"creator_id": seeded_creator.id, "plan": "pro"}).encode()
    event = provider.parse_webhook(raw, None)
    assert event["plan"] == Plan.pro


# ----------------------------------------------------------------- API


def test_api_set_plan_and_subscription(client, seeded_creator):
    resp = client.put(f"/billing/creators/{seeded_creator.id}/plan",
                      json={"plan": "pro"}, headers=_admin())
    assert resp.json()["plan"] == "pro"
    sub = client.get(f"/billing/creators/{seeded_creator.id}/subscription",
                     headers=_admin()).json()
    assert sub["plan"] == "pro"
    assert "usage" in sub


def test_api_draft_gated_for_free_plan(client, seeded_creator, session):
    from sqlalchemy import select
    from cci_core.models import DemandTopic
    from cci_workers.radar import build_radar

    build_radar(seeded_creator.id, backlog=True)
    session.commit()
    topic = session.scalar(select(DemandTopic).where(
        DemandTopic.creator_id == seeded_creator.id))
    # free plan → 402 upgrade required
    resp = client.post(f"/agent/demand/{topic.id}/draft", headers=_admin())
    assert resp.status_code == 402

    # upgrade to pro → allowed
    client.put(f"/billing/creators/{seeded_creator.id}/plan",
               json={"plan": "pro"}, headers=_admin())
    resp = client.post(f"/agent/demand/{topic.id}/draft", headers=_admin())
    assert resp.status_code == 200
    assert resp.json()["draft_id"]


def test_billing_webhook(client, seeded_creator):
    resp = client.post("/billing/webhook",
                       json={"creator_id": seeded_creator.id, "plan": "creator"})
    assert resp.json()["applied"] is True
