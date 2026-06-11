"""API surface: public search, deep links, events, affiliate redirect, admin auth."""
import pytest
from fastapi.testclient import TestClient

from cci_api.main import create_app
from cci_core.config import get_settings


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


def _admin_headers():
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_search_endpoint_returns_results_and_logs_query(client, seeded_creator, session):
    resp = client.get(f"/api/{seeded_creator.handle}/search", params={"q": "price objections"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"]
    assert data["deep_link"].endswith("q=price%20objections") or "q=" in data["deep_link"]
    # demand signal logged
    from sqlalchemy import select
    from cci_core.models import Query

    session.expire_all()
    queries = session.scalars(select(Query).where(Query.creator_id == seeded_creator.id)).all()
    assert any(q.text == "price objections" for q in queries)


def test_search_answer_card_present(client, seeded_creator):
    data = client.get(f"/api/{seeded_creator.handle}/search",
                      params={"q": "how to handle price objections"}).json()
    assert data["answer"] is not None
    if data["answer"]["state"] == "answered":
        assert data["answer"]["citations"]


def test_unknown_creator_404(client):
    assert client.get("/api/nobody/search", params={"q": "x"}).status_code == 404


def test_answer_deep_link_resolution(client, seeded_creator):
    data = client.get(f"/api/{seeded_creator.handle}/search",
                      params={"q": "push day workout"}).json()
    answer_id = data["answer"] and data["answer"]["answer_id"]
    if answer_id:
        resp = client.get(f"/api/{seeded_creator.handle}/answer/{answer_id}")
        assert resp.status_code == 200
        assert resp.json()["answer_id"] == answer_id


def test_affiliate_redirect_tracks_and_302s(client, seeded_creator, session):
    from sqlalchemy import select
    from cci_core.models import Product

    product = session.scalar(select(Product).where(Product.creator_id == seeded_creator.id))
    resp = client.get(f"/api/{seeded_creator.handle}/buy/{product.id}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == product.affiliate_url


def test_admin_requires_token(client):
    assert client.get("/admin/creators").status_code == 401
    assert client.get("/admin/creators", headers=_admin_headers()).status_code == 200


def test_admin_dm_queue_and_decide(client, seeded_creator, session):
    from cci_workers.dm import handle_comment_event

    job_id = handle_comment_event(seeded_creator.id, "api-wh-1",
                                  "what can I eat for breakfast?", "fan-77", "demo-0")
    queue = client.get(f"/admin/creators/{seeded_creator.id}/dm-queue",
                       headers=_admin_headers()).json()
    assert any(j["job_id"] == job_id for j in queue)

    resp = client.post(f"/admin/dm-jobs/{job_id}/decide", json={"approve": True},
                       headers=_admin_headers())
    assert resp.json()["status"] == "approved"
    # deciding twice fails
    resp = client.post(f"/admin/dm-jobs/{job_id}/decide", json={"approve": False},
                       headers=_admin_headers())
    assert resp.status_code == 404


def test_admin_metrics_shape(client, seeded_creator):
    data = client.get(f"/admin/creators/{seeded_creator.id}/metrics",
                      headers=_admin_headers()).json()
    assert {"corpus", "audience", "dm", "monetization"} <= set(data.keys())


def test_radar_mark(client, seeded_creator, session):
    from cci_workers.radar import build_radar
    from sqlalchemy import select
    from cci_core.models import DemandTopic

    build_radar(seeded_creator.id, backlog=True)
    session.expire_all()
    card = session.scalar(select(DemandTopic).where(DemandTopic.creator_id == seeded_creator.id))
    resp = client.post(f"/admin/radar/{card.id}/mark", json={"marked": "useful"},
                       headers=_admin_headers())
    assert resp.status_code == 200
