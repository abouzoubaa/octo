"""Admin endpoint that triggers a native connector sync (YouTube backfill)."""
import pytest
from fastapi.testclient import TestClient

from cci_api.main import create_app
from cci_core.config import get_settings
from cci_core.models import OAuthToken, PlatformAccount


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


def _admin():
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


class _FakeJob:
    id = "job-xyz"


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, func_path, *args, **kwargs):
        self.calls.append((func_path, args))
        return _FakeJob()


def test_sync_native_rejects_unknown_platform(client, creator):
    r = client.post(f"/admin/creators/{creator.id}/sync-native?platform=myspace",
                    headers=_admin())
    assert r.status_code == 400
    assert "native content connector" in r.json()["detail"]


def test_sync_native_requires_authorization(client, creator):
    # youtube is a real connector, but this creator hasn't connected it
    r = client.post(f"/admin/creators/{creator.id}/sync-native?platform=youtube",
                    headers=_admin())
    assert r.status_code == 400
    assert "authorization" in r.json()["detail"]


def test_sync_native_dispatches_when_connected(client, creator, session, monkeypatch):
    import cci_workers.queue as q

    session.add(OAuthToken(creator_id=creator.id, platform="youtube", access_token="tok"))
    session.add(PlatformAccount(creator_id=creator.id, platform="youtube",
                                external_account_id="UC_channel", mode="native"))
    session.commit()
    fake = _FakeQueue()
    monkeypatch.setattr(q, "get_queue", lambda *a, **k: fake)

    r = client.post(f"/admin/creators/{creator.id}/sync-native?platform=youtube",
                    headers=_admin())
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == "job-xyz" and body["channel"] == "UC_channel"
    # dispatched the right worker with (creator_id, platform)
    func_path, args = fake.calls[0]
    assert func_path == "cci_workers.sync_native.sync_native"
    assert args == (creator.id, "youtube")


def test_sync_all_dispatches_authorized_native_accounts(client, creator, session, monkeypatch):
    import cci_workers.queue as q

    # two native accounts (youtube authorized, tiktok authorized), one import-mode
    session.add(OAuthToken(creator_id=creator.id, platform="youtube", access_token="t"))
    session.add(OAuthToken(creator_id=creator.id, platform="tiktok", access_token="t"))
    session.add(PlatformAccount(creator_id=creator.id, platform="youtube", mode="native"))
    session.add(PlatformAccount(creator_id=creator.id, platform="tiktok", mode="native"))
    session.add(PlatformAccount(creator_id=creator.id, platform="instagram", mode="import"))
    session.commit()
    fake = _FakeQueue()
    monkeypatch.setattr(q, "get_queue", lambda *a, **k: fake)

    r = client.post(f"/admin/creators/{creator.id}/sync-all", headers=_admin())
    assert r.status_code == 200
    body = r.json()
    assert body["dispatched"] == ["tiktok", "youtube"] and body["count"] == 2
    dispatched_platforms = {args[1] for _f, args in fake.calls}
    assert dispatched_platforms == {"youtube", "tiktok"}  # not the import-mode IG


def test_connectors_endpoint_reports_last_synced(client, creator, session):
    from datetime import datetime, timezone

    session.add(OAuthToken(creator_id=creator.id, platform="youtube", access_token="tok"))
    session.add(PlatformAccount(
        creator_id=creator.id, platform="youtube", external_account_id="UC",
        mode="native", last_synced_at=datetime(2026, 6, 1, tzinfo=timezone.utc)))
    session.commit()

    r = client.get(f"/admin/creators/{creator.id}/connectors", headers=_admin())
    assert r.status_code == 200
    yt = next(c for c in r.json() if c["platform"] == "youtube")
    assert yt["last_synced_at"].startswith("2026-06-01")
