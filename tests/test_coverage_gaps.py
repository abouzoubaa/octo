"""Coverage for previously-untested high-risk paths + review-fix regressions:
DM dispatcher, webhook signature, enrich pipeline, citation gate firing, PII fix.
"""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from cci_api.main import create_app
from cci_core.config import get_settings
from cci_core.models import Comment, DmJob, DmStatus, OAuthToken, Post


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


# ----------------------------------------------------- DM dispatcher (was untested)


class _FakeIG:
    def __init__(self, *a, **k):
        self.replies, self.dms = [], []

    def reply_to_comment(self, cid, msg):
        self.replies.append((cid, msg))

    def private_reply(self, cid, msg):
        self.dms.append((cid, msg))


def _approved_job(session, creator, *, age_days=1, external="disp-1"):
    c = Comment(creator_id=creator.id, external_id=external, author_pseudonym="a",
                text="q?", is_question=True,
                created_at=datetime.now(timezone.utc) - timedelta(days=age_days))
    session.add(c)
    session.flush()
    j = DmJob(creator_id=creator.id, comment_id=c.id, status=DmStatus.approved,
              public_reply="reply", dm_text="here you go")
    session.add(j)
    session.add(OAuthToken(creator_id=creator.id, platform="instagram", access_token="t"))
    session.commit()
    return j


def test_dispatch_sends_approved(seeded_creator, session, monkeypatch):
    from cci_workers import dm

    job = _approved_job(session, seeded_creator)
    monkeypatch.setattr("cci_core.instagram.InstagramClient", _FakeIG)
    stats = dm.dispatch_approved(seeded_creator.id)
    assert stats["sent"] == 1
    session.expire_all()
    assert session.get(DmJob, job.id).status == DmStatus.sent


def test_dispatch_expires_stale_window(seeded_creator, session, monkeypatch):
    from cci_workers import dm

    job = _approved_job(session, seeded_creator, age_days=10, external="old")  # >7 days
    monkeypatch.setattr("cci_core.instagram.InstagramClient", _FakeIG)
    stats = dm.dispatch_approved(seeded_creator.id)
    assert stats["expired"] == 1
    session.expire_all()
    assert session.get(DmJob, job.id).status == DmStatus.expired


def test_dispatch_ignores_followup_jobs(seeded_creator, session, monkeypatch):
    """Agentic follow-up jobs (comment_id IS NULL) must NOT crash the comment
    dispatcher — they're excluded for the thread dispatcher (review Finding 2/3)."""
    from cci_workers import dm

    session.add(OAuthToken(creator_id=seeded_creator.id, platform="instagram", access_token="t"))
    session.add(DmJob(creator_id=seeded_creator.id, comment_id=None,
                      status=DmStatus.approved, dm_text="follow up", turn=1))
    session.commit()
    monkeypatch.setattr("cci_core.instagram.InstagramClient", _FakeIG)
    stats = dm.dispatch_approved(seeded_creator.id)  # must not raise
    assert stats["sent"] == 0 and stats["failed"] == 0


# ------------------------------------------------ webhook signature (was untested)


def test_webhook_verify_handshake(client):
    token = get_settings().ig_webhook_verify_token
    ok = client.get("/webhooks/instagram", params={
        "hub.mode": "subscribe", "hub.challenge": "42", "hub.verify_token": token})
    assert ok.status_code == 200 and ok.text == "42"
    bad = client.get("/webhooks/instagram", params={
        "hub.mode": "subscribe", "hub.challenge": "42", "hub.verify_token": "wrong"})
    assert bad.status_code == 403


def test_webhook_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "ig_app_secret", "shh")
    body = json.dumps({"entry": []}).encode()
    bad = client.post("/webhooks/instagram", content=body,
                      headers={"x-hub-signature-256": "sha256=deadbeef"})
    assert bad.status_code == 403
    good_sig = "sha256=" + hmac.new(b"shh", body, hashlib.sha256).hexdigest()
    good = client.post("/webhooks/instagram", content=body,
                       headers={"x-hub-signature-256": good_sig})
    assert good.status_code == 200


# ------------------------------------------------ enrich pipeline (was untested)


def test_process_post_runs_pipeline(creator, session):
    """The enrich pipeline (idempotent) writes enrichment + chunks; seed bypasses it."""
    from cci_workers.enrich import process_post

    post = Post(creator_id=creator.id, platform="instagram", external_id="enr-1",
                type="image", caption="3 high-protein breakfasts under 10 minutes")
    session.add(post)
    session.commit()
    stats = process_post(post.id)
    assert stats["enriched"] is True
    assert stats["chunks"] > 0
    # idempotent: second run doesn't re-enrich
    assert process_post(post.id)["enriched"] is False


# ------------------------------------------ citation gate actually fires (was vacuous)


def test_citation_gate_can_fail(seeded_creator, session):
    """Prove the safety-critical citation gate FAILS on a wrong-citation holdout —
    previously nothing verified it could fire."""
    from cci_eval.harness import GATE_CITATIONS, check_gates

    # an answered holdout whose expected post is wrong → citation_correctness 0.0
    summary = {"top3_accuracy": 1.0, "no_answer_accuracy": 1.0,
               "citation_correctness": 0.0, "n_questions": 1}
    failures = check_gates(summary)
    assert any("citation_correctness" in f for f in failures)
    assert GATE_CITATIONS >= 0.9


# ------------------------------------------------ PII over-redaction fix (Finding 4)


def test_pii_preserves_numeric_question_content():
    from cci_core.pii import redact_pii

    # numeric question content must survive (was mangled to [phone] before the fix)
    assert redact_pii("is the 2 - 3 - 4 split worth it?") == "is the 2 - 3 - 4 split worth it?"
    assert redact_pii("around 1.5 - 2.0 g per kg") == "around 1.5 - 2.0 g per kg"
    # a real phone is still redacted
    assert "[phone]" in redact_pii("call +1 (415) 555-1234")
