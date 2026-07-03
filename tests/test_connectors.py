"""Wave L: connector framework + capability registry."""
import pytest
from fastapi.testclient import TestClient

from cci_api.main import create_app
from cci_core.config import get_settings
from cci_core.connectors import (
    CapabilityError,
    capabilities_for,
    get_connector,
    require,
    supported_platforms,
    supports,
)
from cci_core.connectors.base import (
    COMMENTS_READ,
    CONTENT_PUBLISH,
    CONTENT_READ,
    MESSAGES_SEND,
)


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


def _admin():
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


def test_builtin_platforms_registered():
    assert set(supported_platforms()) >= {"instagram", "youtube"}


def test_instagram_has_full_loop():
    caps = capabilities_for("instagram")
    assert {CONTENT_READ, COMMENTS_READ, MESSAGES_SEND, CONTENT_PUBLISH} <= caps


def test_youtube_has_no_dm_messaging():
    caps = capabilities_for("youtube")
    assert CONTENT_READ in caps and COMMENTS_READ in caps
    assert MESSAGES_SEND not in caps  # YouTube has no IG-style DM surface


def test_unknown_platform_empty_capabilities():
    assert get_connector("nope") is None
    assert capabilities_for("nope") == set()


def test_require_raises_for_missing_capability():
    yt = get_connector("youtube")
    assert supports(yt, CONTENT_READ)
    require(yt, CONTENT_READ)  # no raise
    with pytest.raises(CapabilityError):
        require(yt, MESSAGES_SEND)  # YouTube can't DM


def test_reply_not_implemented_is_guarded():
    yt = get_connector("youtube")
    with pytest.raises(NotImplementedError):
        yt.publish_content(None, None)  # base default until a real impl is wired


# ----------------------------------------------------------------- API


def test_platforms_endpoint(client):
    data = client.get("/admin/platforms", headers=_admin()).json()
    platforms = {p["platform"] for p in data}
    assert {"instagram", "youtube"} <= platforms
    ig = next(p for p in data if p["platform"] == "instagram")
    assert "content.read" in ig["capabilities"]


def test_creator_connectors_endpoint(client, seeded_creator, session):
    from cci_core.models import OAuthToken

    session.add(OAuthToken(creator_id=seeded_creator.id, platform="instagram",
                           access_token="t"))
    session.commit()
    data = client.get(f"/admin/creators/{seeded_creator.id}/connectors",
                      headers=_admin()).json()
    assert data and data[0]["platform"] == "instagram"
    assert "content.read" in data[0]["capabilities"]
