"""Locks the cross-cutting review fixes: creator-existence on operator mutations,
webhook fail-safe, radar idempotency, eval vacuous-gate, and input bounds."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from cci_api.main import create_app
from cci_core.config import get_settings
from cci_core.models import DemandTopic, EvalQuestion


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


def _admin():
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


# --------------------------------------------------- creator-existence on mutations


def test_set_token_unknown_creator_404_not_silent_200(client):
    r = client.put("/admin/creators/does-not-exist/token",
                   json={"platform": "instagram", "access_token": "t"}, headers=_admin())
    assert r.status_code == 404  # was a silent 200 with the write discarded at commit


def test_add_product_unknown_creator_404_not_500(client):
    r = client.post("/admin/creators/does-not-exist/products",
                    json={"name": "x", "url": "http://x", "price_cents": 100}, headers=_admin())
    assert r.status_code == 404  # was a leaked 500 (IntegrityError)


def test_trigger_backfill_unknown_creator_404(client):
    r = client.post("/admin/creators/does-not-exist/backfill", headers=_admin())
    assert r.status_code == 404


# --------------------------------------------------- webhook fail-safe (dev/debug)


def test_webhook_bad_json_is_400_not_500(client):
    # debug default → unsigned bodies accepted; a malformed body must 400, not 500
    r = client.post("/webhooks/instagram", content=b"not json",
                    headers={"content-type": "application/json"})
    assert r.status_code == 400


# --------------------------------------------------- radar idempotency


def test_build_radar_is_idempotent(seeded_creator, session):
    from cci_workers.radar import build_radar

    build_radar(seeded_creator.id, backlog=True)
    session.expire_all()
    first = session.scalar(select(func.count(DemandTopic.id)).where(
        DemandTopic.creator_id == seeded_creator.id))
    build_radar(seeded_creator.id, backlog=True)  # re-run must replace, not duplicate
    session.expire_all()
    second = session.scalar(select(func.count(DemandTopic.id)).where(
        DemandTopic.creator_id == seeded_creator.id))
    assert second == first and first > 0


# --------------------------------------------------- eval vacuous-gate


def test_eval_gate_fails_when_nothing_answerable(creator, session):
    from cci_eval.harness import check_gates, run_eval

    # a held-out question with a real expected post, but an EMPTY corpus → the answer
    # card returns no_strong_answer, so the citation gate has nothing to certify.
    session.add(EvalQuestion(creator_id=creator.id, question="what esim for japan?",
                             expected_post_ids=["nonexistent-post"], holdout=True))
    session.commit()
    summary = run_eval(creator.id)
    assert summary["citation_correctness"] is None and summary["holdout_questions"] == 1
    failures = check_gates(summary)
    assert any("vacuous" in f for f in failures)  # fail closed, not a vacuous pass


# --------------------------------------------------- input bounds


def test_dm_dispatch_is_serialized_per_creator(seeded_creator, session):
    """A second concurrent dispatch for the same creator no-ops (advisory lock),
    so the hourly cap can't be bypassed and a job can't be double-sent."""
    import hashlib

    from sqlalchemy import text

    from cci_core.db import get_engine
    from cci_workers.dm import dispatch_approved

    key = int.from_bytes(
        hashlib.blake2b(seeded_creator.id.encode(), digest_size=8).digest(), "big", signed=True)
    conn = get_engine().connect()
    trans = conn.begin()
    assert conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key}).scalar() is True
    try:
        stats = dispatch_approved(seeded_creator.id)  # lock held elsewhere → must skip
        assert stats.get("skipped_locked") is True
    finally:
        trans.rollback()
        conn.close()


def test_public_api_answer_q_length_bounded(client, seeded_creator, session):
    from cci_agent.team import mint_api_key

    _, key = mint_api_key(session, seeded_creator.id, "k", scopes=["answer:read"])
    session.commit()
    r = client.get("/v1/public/answer", params={"q": "x" * 5000},
                   headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 422  # over max_length=500
