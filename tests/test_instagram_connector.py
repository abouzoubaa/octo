"""Instagram native connector — mapping + sync_native, with a fake Graph client
(no httpx / network). Mirrors the YouTube native path so sync_native is uniform."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from cci_core.connectors.base import CapabilityError
from cci_core.connectors.instagram import InstagramConnector
from cci_core.models import Comment, Post


class FakeIgClient:
    """Stand-in for InstagramClient — canned Graph API media/comment dicts."""

    def __init__(self, token):
        assert token == "ig-tok"
        self.replied = []

    def iter_media(self, ig_user_id):
        assert ig_user_id == "IG_USER"
        yield {"id": "m1", "media_type": "VIDEO", "caption": "carry-on packing tips",
               "permalink": "https://instagram.com/p/m1", "media_url": "http://x/m1.mp4",
               "timestamp": "2026-06-01T10:00:00+0000"}
        yield {"id": "m2", "media_type": "CAROUSEL_ALBUM", "caption": "europe esim guide",
               "permalink": "https://instagram.com/p/m2",
               "timestamp": "2026-06-02T10:00:00+0000"}

    def iter_comments(self, media_id):
        if media_id == "m1":
            yield ({"id": "ig-c1", "text": "how do I pick a plan?",
                    "from": {"id": "fan-1", "username": "traveler"},
                    "timestamp": "2026-06-03T10:00:00+0000"}, None)
            yield ({"id": "ig-c2", "text": "love this",
                    "from": {"id": "fan-2"}, "timestamp": "2026-06-03T10:01:00+0000"}, None)

    def reply_to_comment(self, comment_id, message):
        self.replied.append((comment_id, message))
        return {"id": "reply-1"}


def _conn():
    return InstagramConnector(client_factory=FakeIgClient)


def _account():
    return SimpleNamespace(external_account_id="IG_USER", access_token="ig-tok")


def test_backfill_content_maps_media():
    items = _conn().backfill_content(_account())
    assert [i.external_id for i in items] == ["m1", "m2"]
    assert items[0].kind == "video" and items[1].kind == "carousel"
    assert items[0].posted_at is not None and "packing" in items[0].caption


def test_backfill_interactions_maps_comments():
    its = _conn().backfill_interactions(_account(), "m1")
    assert [i.external_id for i in its] == ["ig-c1", "ig-c2"]
    assert its[0].author_external_id == "fan-1"


def test_ts_tolerates_garbage_values():
    # non-string / malformed timestamps must not abort a backfill
    assert InstagramConnector._ts(12345) is None
    assert InstagramConnector._ts(None) is None
    assert InstagramConnector._ts("not-a-date") is None
    assert InstagramConnector._ts("2026-06-01T10:00:00+0000") is not None


def test_reply_requires_capability():
    class NoReply(InstagramConnector):
        def capabilities(self):
            return {"content.read"}

    with pytest.raises(CapabilityError):
        NoReply(client_factory=FakeIgClient).reply_to_interaction(_account(), "ig-c1", "hi")


def test_sync_native_instagram_persists(creator, session):
    from cci_workers.sync_native import sync_native

    stats = sync_native(creator.id, "instagram", connector=_conn(), account=_account())
    assert stats["posts"] == 2 and stats["comments"] == 2 and stats["questions"] == 1
    session.expire_all()
    posts = session.scalars(select(Post).where(
        Post.creator_id == creator.id, Post.platform == "instagram")).all()
    assert {p.external_id for p in posts} == {"m1", "m2"}
    comments = session.scalars(select(Comment).where(
        Comment.creator_id == creator.id)).all()
    assert {c.external_id for c in comments} == {"ig-c1", "ig-c2"}
    assert all(c.author_pseudonym not in ("fan-1", "fan-2") for c in comments)  # pseudonymised
