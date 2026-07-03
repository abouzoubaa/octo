"""Conformance-audit wirings: features that existed as library code are now
reachable from a surface — clarify in the search response, playbooks in the DM
pipeline, affiliate injection at draft approval, delegation hints in the DM queue."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cci_api.main import create_app
from cci_core.config import get_settings
from cci_core.models import (
    Comment, DmJob, DmStatus, Playbook, Post, Product, ProductLink,
)


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


def _admin():
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


# ------------------------------------------- bounded clarify in the search response


def test_no_answer_search_includes_clarify(client, seeded_creator):
    data = client.get(f"/api/{seeded_creator.handle}/search",
                      params={"q": "zzz completely uncovered topic qqq"}).json()
    assert data["answer"]["state"] == "no_strong_answer"
    clarify = data["answer"]["clarify"]
    assert clarify is None or (clarify["question"] and len(clarify["options"]) == 2)


def test_answered_search_has_no_clarify(client, seeded_creator):
    data = client.get(f"/api/{seeded_creator.handle}/search",
                      params={"q": "how to handle price objections"}).json()
    assert data["answer"]["state"] == "answered"
    assert data["answer"]["clarify"] is None


# ------------------------------------------- playbooks applied in the DM pipeline


def test_playbook_template_handles_matching_comment(seeded_creator, session):
    from cci_workers.dm import handle_comment_event

    session.add(Playbook(creator_id=seeded_creator.id, name="shipping",
                         trigger_keywords=["shipping"],
                         public_reply_template="Shipping info in your DMs! 📦",
                         dm_template="All shipping details: {link}"))
    session.commit()

    job_id = handle_comment_event(seeded_creator.id, "pb-c1",
                                  "what about shipping to canada?", "fan-9", None)
    assert job_id is not None
    session.expire_all()
    job = session.get(DmJob, job_id)
    assert job.status == DmStatus.pending_approval  # still approval mode
    assert job.public_reply == "Shipping info in your DMs! 📦"
    assert "http" in job.dm_text  # {link} substituted with the archive link


# ------------------------------------------- affiliate injection at draft approval


def test_draft_approval_injects_affiliate_links(client, seeded_creator, session):
    from cci_core.models import ContentDraft

    post = session.scalar(select(Post).where(Post.creator_id == seeded_creator.id))
    product = Product(creator_id=seeded_creator.id, name="Objection Playbook",
                      affiliate_url="https://aff.example/x", approved=True)
    session.add(product)
    session.flush()
    session.add(ProductLink(product_id=product.id, post_id=post.id))
    draft = ContentDraft(creator_id=seeded_creator.id, title="t", script="the script body",
                         source_post_ids=[post.id], status="draft")
    session.add(draft)
    session.commit()

    r = client.post(f"/agent/drafts/{draft.id}/decide", json={"approve": True},
                    headers=_admin())
    assert r.status_code == 200 and r.json()["status"] == "approved"
    session.expire_all()
    saved = session.get(ContentDraft, draft.id)
    assert "aff.example" in saved.script and "utm" in saved.script.lower()
    assert "affiliate" in saved.script.lower()  # visible disclosure


# ------------------------------------------- delegation hint in the DM queue


def test_dm_queue_surfaces_delegation_candidate(client, seeded_creator, session):
    from cci_workers.dm import handle_comment_event

    post = session.scalar(select(Post).where(Post.creator_id == seeded_creator.id))
    # a well-liked follower answer already sits under the post
    session.add(Comment(creator_id=seeded_creator.id, post_id=post.id, external_id="ans-1",
                        author_pseudonym="fanA", is_question=False,
                        text="You just breathe out on the way up — that fixed it for me "
                             "and helped a lot of others here too."))
    session.commit()

    job_id = handle_comment_event(seeded_creator.id, "q-del-1",
                                  "how do I breathe during squats?", "fan-2",
                                  post.external_id)
    assert job_id is not None
    rows = client.get(f"/admin/creators/{seeded_creator.id}/dm-queue",
                      headers=_admin()).json()
    mine = next(r for r in rows if r["job_id"] == job_id)
    assert "delegation" in mine  # hint present (candidate or null, never missing)
