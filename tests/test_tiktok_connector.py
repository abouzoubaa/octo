"""TikTok native connector (Display API v2) — archive vs full-loop, exercised with
a fake transport (no httpx). Archive ingests content only; full-loop adds comments."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from cci_core.connectors.base import CapabilityError
from cci_core.connectors.tiktok import TikTokConnector
from cci_core.models import Comment, Post


class FakeTransport:
    def __init__(self):
        self.posted = []

    def post(self, path, params, json, token):
        assert token == "tt-tok"
        self.posted.append((path, json))
        if path == "video/list/":
            if json.get("cursor"):  # second page ends the walk
                return {"data": {"videos": [], "has_more": False}}
            return {"data": {"videos": [
                {"id": "v1", "video_description": "30s europe packing hack",
                 "create_time": 1717236000, "share_url": "https://tiktok.com/@x/v1",
                 "cover_image_url": "http://x/v1.jpg"},
                {"id": "v2", "video_description": "best travel esim",
                 "create_time": 1717322400, "share_url": "https://tiktok.com/@x/v2"},
            ], "cursor": 20, "has_more": True}}
        if path == "video/comment/list/":
            vid = json["video_id"]  # distinct comment ids per video
            return {"data": {"comments": [
                {"id": f"{vid}-tc1", "text": "which esim for japan?",
                 "create_time": 1717400000, "user": {"id": "ttuser1"}},
                {"id": f"{vid}-tc2", "text": "saved!", "create_time": 1717400100,
                 "user": {"id": "ttuser2"}},
            ], "has_more": False}}
        if path == "video/comment/reply/":
            return {"data": {"comment_id": "reply-1"}}
        raise AssertionError(path)


def _account():
    return SimpleNamespace(external_account_id="tt_open_id", access_token="tt-tok")


# ----------------------------------------------------------------- archive mode


def test_archive_backfill_content_maps_videos():
    conn = TikTokConnector(transport=FakeTransport())  # archive default
    items = conn.backfill_content(_account())
    assert [i.external_id for i in items] == ["v1", "v2"]
    assert items[0].kind == "short"
    assert items[0].permalink == "https://tiktok.com/@x/v1"
    assert items[0].posted_at is not None  # epoch parsed


class ZeroCursorTransport:
    """First page returns cursor 0 with has_more=True — the walk must continue
    (a 0 cursor is valid; only None means done)."""

    def __init__(self):
        self.pages = 0

    def post(self, path, params, json, token):
        assert path == "video/list/"
        self.pages += 1
        if self.pages == 1:
            return {"data": {"videos": [{"id": "z1"}], "cursor": 0, "has_more": True}}
        return {"data": {"videos": [{"id": "z2"}], "has_more": False}}


def test_zero_cursor_does_not_stop_walk_early():
    conn = TikTokConnector(transport=ZeroCursorTransport())
    items = conn.backfill_content(_account())
    assert [i.external_id for i in items] == ["z1", "z2"]  # both pages walked


def test_archive_has_no_comment_access():
    conn = TikTokConnector(transport=FakeTransport())  # archive
    assert conn.backfill_interactions(_account(), "v1") == []  # no comment API in archive


def test_archive_cannot_reply():
    conn = TikTokConnector(transport=FakeTransport())
    with pytest.raises(CapabilityError):
        conn.reply_to_interaction(_account(), "tc1", "hi")


# ----------------------------------------------------------------- full loop


def test_full_loop_backfill_interactions_maps_comments():
    conn = TikTokConnector(full_loop=True, transport=FakeTransport())
    its = conn.backfill_interactions(_account(), "v1")
    assert [i.external_id for i in its] == ["v1-tc1", "v1-tc2"]
    assert its[0].author_external_id == "ttuser1"


def test_full_loop_reply_posts():
    t = FakeTransport()
    TikTokConnector(full_loop=True, transport=t).reply_to_interaction(_account(), "tc1", "→ Airalo")
    assert t.posted[-1][0] == "video/comment/reply/"
    assert t.posted[-1][1]["comment_id"] == "tc1"


# ----------------------------------------------------------------- sync_native


def test_sync_native_tiktok_archive_persists_content_only(creator, session):
    from cci_workers.sync_native import sync_native

    stats = sync_native(creator.id, "tiktok",
                        connector=TikTokConnector(transport=FakeTransport()),
                        account=_account())
    assert stats["posts"] == 2 and stats["comments"] == 0  # archive: content, no comments
    session.expire_all()
    posts = session.scalars(select(Post).where(
        Post.creator_id == creator.id, Post.platform == "tiktok")).all()
    assert {p.external_id for p in posts} == {"v1", "v2"}
    assert session.scalars(select(Comment).where(Comment.creator_id == creator.id)).all() == []


def test_sync_native_tiktok_full_loop_persists_comments(creator, session):
    from cci_workers.sync_native import sync_native

    stats = sync_native(creator.id, "tiktok",
                        connector=TikTokConnector(full_loop=True, transport=FakeTransport()),
                        account=_account())
    assert stats["posts"] == 2 and stats["comments"] == 4  # 2 comments per video
    assert stats["questions"] == 2  # one "which esim…?" per video


def test_sync_native_builds_connector_from_account_full_loop(creator, session, monkeypatch):
    """With no explicit connector, sync_native reads the account's full_loop grant to
    decide whether to ingest comments (per-account capability, not per-platform)."""
    from cci_core.models import OAuthToken, PlatformAccount
    from cci_workers import sync_native as sn
    from cci_workers.sync_native import sync_native

    session.add(OAuthToken(creator_id=creator.id, platform="tiktok", access_token="tt-tok"))
    session.add(PlatformAccount(creator_id=creator.id, platform="tiktok", mode="native",
                                external_account_id="tt_open_id", full_loop=True))
    session.commit()
    # force the real-connector path (connector=None) but with a fake transport
    monkeypatch.setattr(sn, "get_connector",
                        lambda platform, *, full_loop=False: TikTokConnector(
                            full_loop=full_loop, transport=FakeTransport()))
    stats = sync_native(creator.id, "tiktok")  # no connector/account passed
    assert stats["posts"] == 2 and stats["comments"] == 4  # full_loop → comments ingested
