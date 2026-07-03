"""Wave H: webhook idempotency, AI version registry, spam filter, RLS."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from cci_api.main import create_app
from cci_core.config import get_settings
from cci_retrieval.intent import INTENT_SPAM, detect_intent, is_spam


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


# ----------------------------------------------------------- spam filter


def test_is_spam_detects_promo_and_lures():
    assert is_spam("follow me for free followers!!")
    assert is_spam("DM me to earn $$$ with crypto giveaway")
    assert is_spam("check my profile www.scam.com to buy followers")
    assert is_spam("🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥")  # repeated-char engagement bait


def test_is_spam_does_not_flag_genuine_questions():
    assert not is_spam("where's the post about high protein breakfast?")
    assert not is_spam("how much protein should I eat?")


def test_detect_intent_marks_spam_first():
    assert detect_intent("follow me for free followers").intent == INTENT_SPAM
    # spam is excluded from questions → won't feed demand or trigger a DM


def test_spam_comment_not_a_question(seeded_creator, session):
    from cci_core.pii import redact_pii
    from cci_retrieval.intent import INTENT_QUESTION

    text_ = redact_pii("earn $5000 a month, DM me to earn now!")
    intent = detect_intent(text_)
    assert intent.intent != INTENT_QUESTION  # never counted as demand


# ----------------------------------------------------------- webhook idempotency


def test_webhook_dedupes_redelivered_event(client, seeded_creator, session, monkeypatch):
    # stub the enqueue (no Redis in tests) — we're testing the idempotency gate,
    # which runs BEFORE the enqueue
    import cci_api.routers.webhooks as wh

    monkeypatch.setattr(wh, "_enqueue_comment", lambda ig_user_id, value: 1)
    # register the creator's IG id so the webhook resolves
    seeded_creator.ig_user_id = "ig-webhook-1"
    session.commit()
    settings = get_settings()
    body = json.dumps({"entry": [{"id": "ig-webhook-1", "changes": [
        {"field": "comments", "value": {"id": "evt-123", "text": "where is the reel?",
                                        "from": {"id": "fan1"}}}]}]}).encode()
    headers = {}
    if settings.ig_app_secret:
        import hashlib
        import hmac
        headers["x-hub-signature-256"] = "sha256=" + hmac.new(
            settings.ig_app_secret.encode(), body, hashlib.sha256).hexdigest()

    first = client.post("/webhooks/instagram", content=body, headers=headers).json()
    second = client.post("/webhooks/instagram", content=body, headers=headers).json()
    assert first["queued"] == 1
    assert second["queued"] == 0  # redelivery of evt-123 is skipped

    from cci_core.models import WebhookEvent
    session.expire_all()
    n = session.scalar(select(WebhookEvent).where(WebhookEvent.external_id == "evt-123"))
    assert n is not None


# ----------------------------------------------------------- version registry


def test_version_registry_endpoint(client):
    data = client.get("/admin/versions",
                      headers={"Authorization": f"Bearer {get_settings().admin_token}"}).json()
    assert {"llm", "embeddings", "transcription", "ocr", "rerank"} <= set(data.keys())
    assert "dims" in data["embeddings"]


# ----------------------------------------------------------- RLS enforcement


def test_rls_isolates_creators_under_restricted_role(seeded_creator, session):
    """Prove RLS actually blocks cross-creator reads when the connection is a
    NON-superuser role with app.creator_id set. (The test's default role is a
    superuser and bypasses RLS, so we create a restricted role to verify.)"""
    import sqlalchemy as sa

    from cci_core.config import get_settings
    from cci_core.rls import enable_rls

    enable_rls()
    # grant the restricted role access to the tables (RLS still applies to it)
    session.execute(text("DROP ROLE IF EXISTS sift_app_test"))
    session.execute(text("CREATE ROLE sift_app_test LOGIN PASSWORD 'x' NOSUPERUSER"))
    session.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO sift_app_test"))
    session.commit()

    url = sa.engine.make_url(get_settings().database_url).set(
        username="sift_app_test", password="x")
    eng = sa.create_engine(url)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT set_config('app.creator_id', :c, false)"),
                         {"c": seeded_creator.id})
            mine = conn.execute(text(
                "SELECT count(*) FROM comments")).scalar()
            assert mine > 0  # my own rows are visible
            conn.execute(text("SELECT set_config('app.creator_id', 'someone-else', false)"))
            theirs = conn.execute(text("SELECT count(*) FROM comments")).scalar()
            assert theirs == 0  # another creator's scope sees nothing — RLS enforced
    finally:
        eng.dispose()
        session.execute(text("DROP OWNED BY sift_app_test"))
        session.execute(text("DROP ROLE IF EXISTS sift_app_test"))
        session.commit()
