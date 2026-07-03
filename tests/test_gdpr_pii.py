"""PII redaction + GDPR export/erasure."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cci_api.main import create_app
from cci_core.config import get_settings
from cci_core.gdpr import (
    delete_creator,
    erase_audience_member,
    export_creator_data,
    forget_waitlist_email,
)
from cci_core.models import Comment, Creator, Outcome, WaitlistEntry
from cci_core.pii import has_pii, redact_pii
from cci_core.privacy import pseudonymize


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=True)


def _admin():
    return {"Authorization": f"Bearer {get_settings().admin_token}"}


# ----------------------------------------------------------------- PII


def test_redact_email_phone_digits():
    assert redact_pii("mail me at a.b@x.com") == "mail me at [email]"
    assert "[phone]" in redact_pii("call +1 (415) 555-1234 today")
    assert redact_pii("card 4111111111111111") == "card [number]"
    assert redact_pii("what's a good breakfast?") == "what's a good breakfast?"


def test_has_pii():
    assert has_pii("reach me: x@y.com")
    assert not has_pii("how much protein per day")


def test_redact_none_passthrough():
    assert redact_pii(None) is None
    assert redact_pii("") == ""


# ----------------------------------------------------------------- export


def test_export_bundle_shape(seeded_creator, session):
    data = export_creator_data(session, seeded_creator.id)
    assert data["creator"]["handle"] == seeded_creator.handle
    assert isinstance(data["posts"], list) and data["posts"]
    assert "comments" in data and "note" in data


def test_export_unknown_creator(session):
    assert export_creator_data(session, "nope") == {}


# ----------------------------------------------------------------- erasure


def test_delete_creator_cascades(seeded_creator, session):
    cid = seeded_creator.id
    assert session.scalars(select(Comment).where(Comment.creator_id == cid)).first()
    assert delete_creator(session, cid)
    session.flush()
    assert session.get(Creator, cid) is None
    assert session.scalars(select(Comment).where(Comment.creator_id == cid)).first() is None


def test_erase_audience_member(seeded_creator, session):
    pseudo = pseudonymize("fan-xyz", seeded_creator.id)
    session.add(Comment(creator_id=seeded_creator.id, external_id="e1",
                        author_pseudonym=pseudo, text="hi", is_question=True))
    session.add(Outcome(creator_id=seeded_creator.id, source="comment",
                        asker_pseudonym=pseudo))
    session.flush()
    stats = erase_audience_member(session, seeded_creator.id, pseudo)
    assert stats["comments"] == 1 and stats["outcomes"] == 1


def test_forget_waitlist_email(seeded_creator, session):
    session.add(WaitlistEntry(creator_id=seeded_creator.id, email="lead@x.com", topic="t"))
    session.flush()
    assert forget_waitlist_email(session, seeded_creator.id, "lead@x.com") == 1


# ----------------------------------------------------------------- API


def test_api_export_and_erase(client, seeded_creator):
    cid = seeded_creator.id
    assert client.get(f"/admin/creators/{cid}/export", headers=_admin()).status_code == 200
    assert client.delete(f"/admin/creators/{cid}", headers=_admin()).json()["erased"] is True
    # gone afterwards
    assert client.get(f"/admin/creators/{cid}/export", headers=_admin()).status_code == 404
