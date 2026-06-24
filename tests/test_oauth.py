"""OAuth onboarding: state signing, callback validation, token refresh."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from cci_api.main import create_app
from cci_api.routers.oauth import _sign_state, _verify_state


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


def test_state_sign_verify_roundtrip():
    state = _sign_state("alex")
    assert _verify_state(state) == "alex"


def test_state_tamper_rejected():
    assert _verify_state("alex.deadbeefdeadbeef") is None  # forged MAC
    assert _verify_state("nostatehere") is None


def test_callback_rejects_forged_state(client):
    resp = client.get("/oauth/instagram/callback",
                      params={"code": "x", "state": "alex.forged"},
                      follow_redirects=False)
    assert resp.status_code == 400


def test_callback_rejects_denied_authorization(client):
    resp = client.get("/oauth/instagram/callback",
                      params={"error": "access_denied", "state": _sign_state("alex")},
                      follow_redirects=False)
    assert resp.status_code == 400


def test_start_requires_configured_app(client):
    # no IG app id configured in tests → 503, not a crash
    resp = client.get("/oauth/instagram/start", params={"handle": "alex"},
                      follow_redirects=False)
    assert resp.status_code == 503


def test_refresh_due_tokens_picks_expiring(seeded_creator, session, monkeypatch):
    from cci_core.models import OAuthToken
    from cci_workers import refresh_tokens

    soon = datetime.now(timezone.utc) + timedelta(days=3)  # within renewal window
    session.add(OAuthToken(creator_id=seeded_creator.id, platform="instagram",
                           access_token="old-token", expires_at=soon))
    session.commit()

    monkeypatch.setattr(refresh_tokens, "refresh_long_lived",
                        lambda t: {"access_token": "fresh-token", "expires_in": 5184000})
    stats = refresh_tokens.refresh_due_tokens()
    assert stats["refreshed"] == 1

    session.expire_all()
    tok = session.scalar(
        __import__("sqlalchemy").select(OAuthToken).where(
            OAuthToken.creator_id == seeded_creator.id))
    assert tok.access_token == "fresh-token"


def test_refresh_skips_healthy_tokens(seeded_creator, session, monkeypatch):
    from cci_core.models import OAuthToken
    from cci_workers import refresh_tokens

    far = datetime.now(timezone.utc) + timedelta(days=55)  # plenty of life left
    session.add(OAuthToken(creator_id=seeded_creator.id, platform="instagram",
                           access_token="healthy", expires_at=far))
    session.commit()
    assert refresh_tokens.refresh_due_tokens()["checked"] == 0
