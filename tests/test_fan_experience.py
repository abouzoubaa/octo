"""Wave C: Outcome Memory (did-this-help) + fan experience + demand cohort."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cci_api.main import create_app
from cci_core.models import Outcome


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


@pytest.fixture()
def radar(seeded_creator, session):
    from cci_workers.radar import build_radar

    build_radar(seeded_creator.id, backlog=True)
    session.commit()
    return seeded_creator


# ----------------------------------------------------------- demand cohort


def test_waitlist_returns_cohort_size(client, seeded_creator):
    h = seeded_creator.handle
    r1 = client.post(f"/api/{h}/waitlist", json={"email": "a@x.com", "topic": "carb cycling"})
    assert r1.json()["cohort_size"] == 1
    r2 = client.post(f"/api/{h}/waitlist", json={"email": "b@x.com", "topic": "carb cycling tips"})
    assert r2.json()["cohort_size"] == 2  # same topic cohort grows


def test_open_cohorts_lists_counts(client, seeded_creator):
    h = seeded_creator.handle
    client.post(f"/api/{h}/waitlist", json={"email": "a@x.com", "topic": "sleep"})
    client.post(f"/api/{h}/waitlist", json={"email": "b@x.com", "topic": "sleep"})
    cohorts = client.get(f"/api/{h}/cohorts").json()
    assert cohorts and cohorts[0]["topic"] == "sleep"
    assert cohorts[0]["people_waiting"] == 2


# ----------------------------------------------------------- fan experience


def test_most_asked_questions(client, radar):
    popular = client.get(f"/api/{radar.handle}/popular").json()
    assert popular
    assert "question" in popular[0]


def test_browse_topics(client, seeded_creator, session):
    # enrichment topics power topic browsing; process a post to create them
    from cci_core.models import Post
    from cci_workers.enrich import process_post

    post = Post(creator_id=seeded_creator.id, platform="instagram", external_id="topic-1",
                type="image", caption="high protein breakfast meal prep ideas")
    session.add(post)
    session.commit()
    process_post(post.id)
    topics = client.get(f"/api/{seeded_creator.handle}/topics").json()
    assert isinstance(topics, list)
    if topics:
        assert "topic" in topics[0] and "posts" in topics[0]


# ----------------------------------------------------------- Outcome Memory


def test_answer_feedback_resolves_outcome(client, seeded_creator, session):
    # run a search to create an Outcome with an answer_id
    data = client.get(f"/api/{seeded_creator.handle}/search",
                      params={"q": "how to handle price objections"}).json()
    answer_id = data["answer"] and data["answer"]["answer_id"]
    if not answer_id:
        pytest.skip("no answer produced for this query")
    resp = client.post(f"/api/{seeded_creator.handle}/feedback",
                       json={"answer_id": answer_id, "helpful": True})
    assert resp.json()["ok"] is True
    session.expire_all()
    outcome = session.scalar(select(Outcome).where(Outcome.answer_id == answer_id))
    assert outcome.stage == "resolved"
    assert outcome.result["helpful"] is True


def test_feedback_unknown_answer_is_safe(client, seeded_creator):
    # feedback on an unknown answer still 200s (just logs the event)
    resp = client.post(f"/api/{seeded_creator.handle}/feedback",
                       json={"answer_id": "nope", "helpful": False})
    assert resp.status_code == 200
