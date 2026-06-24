"""Observability + rate limiting: metrics, request id, throttling."""
import pytest
from fastapi.testclient import TestClient

from cci_api.main import create_app
from cci_core.config import get_settings


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


def test_request_id_header(client):
    resp = client.get("/healthz")
    assert resp.headers.get("X-Request-ID")


def test_metrics_endpoint(client):
    client.get("/healthz")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "sift_requests_total" in resp.text


def test_rate_limit_public_search(client, seeded_creator, monkeypatch):
    # tighten the limit so the test is fast and deterministic
    s = get_settings()
    monkeypatch.setattr(s, "public_rate_limit_per_min", 3)
    # reset the limiter window for a clean count
    from cci_api import observability

    observability._hits.clear()

    path = f"/api/{seeded_creator.handle}/search"
    codes = [client.get(path, params={"q": "protein"}).status_code for _ in range(5)]
    assert codes.count(429) >= 1  # throttled after the cap
    assert codes[0] == 200  # first ones allowed


def test_rate_limit_disabled_when_zero(client, seeded_creator, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_rate_limit_per_min", 0)
    from cci_api import observability

    observability._hits.clear()
    path = f"/api/{seeded_creator.handle}/search"
    codes = [client.get(path, params={"q": "x"}).status_code for _ in range(8)]
    assert 429 not in codes  # off → never throttles
