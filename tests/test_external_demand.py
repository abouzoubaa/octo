"""Wave O: external demand sources feed Demand Radar (cross-platform synthesis)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cci_api.main import create_app
from cci_core.config import get_settings
from cci_core.connectors import capabilities_for
from cci_core.connectors.base import COMMENTS_READ, DEMAND_READ
from cci_core.models import Comment, DemandTopic, ExternalSignal, Post
from cci_workers.radar import build_radar


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


def _admin():
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


# ----------------------------------------------------------- demand-source connectors


def test_newsletter_is_a_demand_source():
    caps = capabilities_for("newsletter")
    assert DEMAND_READ in caps
    assert COMMENTS_READ not in caps  # pure demand source, not a content platform


def test_demand_sources_registered():
    from cci_core.connectors import supported_platforms

    assert {"newsletter", "podcast", "discord"} <= set(supported_platforms())


# ----------------------------------------------------------- external signals → radar


def test_external_signals_cluster_into_demand(seeded_creator, session):
    # the same question asked via newsletter + a comment → one cross-platform cluster
    session.add(ExternalSignal(creator_id=seeded_creator.id, platform="newsletter",
                               text="how do I handle price objections with clients",
                               is_question=True))
    session.commit()  # build_radar runs in its own session — must see committed rows
    build_radar(seeded_creator.id, backlog=True)
    session.expire_all()
    topics = session.scalars(select(DemandTopic).where(
        DemandTopic.creator_id == seeded_creator.id)).all()
    # the newsletter ask shows up in a topic's source breakdown
    assert any((t.source_breakdown or {}).get("newsletter") for t in topics)


def test_demand_segment_everywhere_with_external(creator, session):
    # an IG comment + a newsletter reply on the same topic → 'everywhere'
    post = Post(creator_id=creator.id, platform="instagram", external_id="seg-ig", type="reel")
    session.add(post)
    session.flush()
    session.add(Comment(creator_id=creator.id, post_id=post.id, external_id="seg-c",
                        author_pseudonym="a", text="best travel esim for europe trips",
                        is_question=True))
    session.add(ExternalSignal(creator_id=creator.id, platform="newsletter",
                               text="best travel esim for europe trips please", is_question=True))
    session.commit()  # build_radar runs in its own session — must see committed rows
    build_radar(creator.id, backlog=True)
    session.expire_all()
    topics = session.scalars(select(DemandTopic).where(
        DemandTopic.creator_id == creator.id)).all()
    assert any(t.demand_segment == "everywhere" for t in topics)


# ----------------------------------------------------------- intake endpoint


def test_external_signal_intake_redacts_and_filters(client, seeded_creator):
    # PII redacted, spam excluded from demand
    ok = client.post(f"/agent/creators/{seeded_creator.id}/external-signal",
                     json={"platform": "newsletter",
                           "text": "reply to me at fan@example.com about carb cycling"},
                     headers=_admin())
    assert ok.status_code == 200 and ok.json()["is_question"] is True

    spam = client.post(f"/agent/creators/{seeded_creator.id}/external-signal",
                       json={"platform": "newsletter", "text": "follow me for free followers!!"},
                       headers=_admin())
    assert spam.json()["is_question"] is False  # spam never becomes demand


def test_external_signal_rejects_non_demand_platform(client, seeded_creator):
    resp = client.post(f"/agent/creators/{seeded_creator.id}/external-signal",
                       json={"platform": "instagram", "text": "hi"}, headers=_admin())
    assert resp.status_code == 422  # instagram is a content platform, not a demand source
