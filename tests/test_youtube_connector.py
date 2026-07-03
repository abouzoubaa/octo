"""Live YouTube connector (native ingest) — exercised end-to-end with a fake HTTP
transport, so no network calls. Covers mapping (content + comments), the reply
action + capability guard, and the native-sync worker that persists into Sift models.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from cci_core.connectors.base import CapabilityError
from cci_core.connectors.youtube import YouTubeConnector
from cci_core.models import Comment, Post


class FakeTransport:
    """Stand-in for YouTubeTransport — returns canned YouTube Data API v3 payloads
    and records writes, so the connector is fully tested without httpx/network."""

    def __init__(self):
        self.posted = []

    def get(self, path, params, token):
        assert token == "tok-123"  # connector forwards the decrypted access token
        if path == "channels":
            return {"items": [{"contentDetails": {
                "relatedPlaylists": {"uploads": "UU_uploads"}}}]}
        if path == "playlistItems":
            assert params["playlistId"] == "UU_uploads"
            if params.get("pageToken"):  # second page ends the walk
                return {"items": []}
            return {"items": [
                {"snippet": {"title": "Best travel eSIM", "description": "regional coverage tips",
                             "publishedAt": "2026-06-01T10:00:00Z"},
                 "contentDetails": {"videoId": "vid-1"}},
                {"snippet": {"title": "Packing carry-on only",
                             "publishedAt": "2026-06-02T10:00:00Z",
                             "resourceId": {"videoId": "vid-2"}}},
            ], "nextPageToken": "PAGE2"}
        if path == "commentThreads":
            if params["videoId"] == "vid-1":
                return {"items": [
                    {"snippet": {"topLevelComment": {"id": "c-1", "snippet": {
                        "textOriginal": "how do I pick a plan for europe?",
                        "authorChannelId": {"value": "UCfan1"},
                        "publishedAt": "2026-06-03T09:00:00Z"}}}},
                    {"snippet": {"topLevelComment": {"id": "c-2", "snippet": {
                        "textDisplay": "great video!",
                        "authorChannelId": {"value": "UCfan2"},
                        "publishedAt": "2026-06-03T09:05:00Z"}}}},
                ]}
            return {"items": []}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, params, json, token):
        self.posted.append((path, json, token))
        return {"id": "reply-1", "snippet": json["snippet"]}


def _conn():
    return YouTubeConnector(transport=FakeTransport())


def _account():
    return SimpleNamespace(external_account_id="UC_channel", access_token="tok-123")


# ----------------------------------------------------------------- mapping


def test_backfill_content_maps_videos():
    items = _conn().backfill_content(_account())
    assert [i.external_id for i in items] == ["vid-1", "vid-2"]
    assert items[0].permalink == "https://www.youtube.com/watch?v=vid-1"
    assert "regional coverage" in items[0].caption
    assert items[0].posted_at is not None and items[0].kind == "video"


def test_sync_content_returns_cursor():
    items, cursor = _conn().sync_content(_account())
    assert cursor == "PAGE2" and len(items) == 2


class PagedTransport(FakeTransport):
    """Two pages of uploads, then a comments page that 403s (comments disabled)."""

    def get(self, path, params, token):
        if path == "channels":
            return {"items": [{"contentDetails": {
                "relatedPlaylists": {"uploads": "UU_uploads"}}}]}
        if path == "playlistItems":
            if not params.get("pageToken"):
                return {"items": [{"snippet": {"title": "v1"},
                                   "contentDetails": {"videoId": "vid-1"}}],
                        "nextPageToken": "P2"}
            return {"items": [{"snippet": {"title": "v2"},
                               "contentDetails": {"videoId": "vid-2"}}]}  # no nextPageToken
        if path == "commentThreads":
            import httpx
            req = httpx.Request("GET", "https://x/commentThreads")
            raise httpx.HTTPStatusError("forbidden", request=req,
                                        response=httpx.Response(403, request=req))
        raise AssertionError(path)


def test_backfill_content_paginates_all_pages():
    items = YouTubeConnector(transport=PagedTransport()).backfill_content(_account())
    assert [i.external_id for i in items] == ["vid-1", "vid-2"]  # both pages walked


def test_sync_native_survives_comments_disabled(creator, session):
    """A 403 on one video's comments must not abort the whole channel backfill."""
    from cci_workers.sync_native import sync_native

    stats = sync_native(creator.id, "youtube",
                        connector=YouTubeConnector(transport=PagedTransport()),
                        account=_account())
    assert stats["posts"] == 2  # both videos still ingested despite the 403
    assert stats["comments"] == 0


def test_backfill_interactions_maps_comments():
    its = _conn().backfill_interactions(_account(), "vid-1")
    assert [i.external_id for i in its] == ["c-1", "c-2"]
    assert its[0].text.startswith("how do I pick")
    assert its[0].author_external_id == "UCfan1"
    assert its[1].text == "great video!"  # textDisplay fallback


def test_reply_posts_and_requires_capability():
    t = FakeTransport()
    conn = YouTubeConnector(transport=t)
    conn.reply_to_interaction(_account(), "c-1", "Here's how →")
    assert t.posted and t.posted[0][0] == "comments"
    assert t.posted[0][1]["snippet"]["parentId"] == "c-1"


def test_reply_capability_guard():
    class NoReply(YouTubeConnector):
        def capabilities(self):
            return {"content.read"}  # no comments.reply

    with pytest.raises(CapabilityError):
        NoReply(transport=FakeTransport()).reply_to_interaction(_account(), "c-1", "hi")


# ----------------------------------------------------------------- native sync worker


def test_sync_native_persists_posts_and_comments(creator, session):
    from cci_workers.sync_native import sync_native

    stats = sync_native(creator.id, "youtube",
                        connector=_conn(), account=_account())
    assert stats["posts"] == 2
    assert stats["comments"] == 2
    assert stats["questions"] == 1  # only the "how do I…?" comment

    session.expire_all()
    posts = session.scalars(select(Post).where(
        Post.creator_id == creator.id, Post.platform == "youtube")).all()
    assert {p.external_id for p in posts} == {"vid-1", "vid-2"}
    comments = session.scalars(select(Comment).where(
        Comment.creator_id == creator.id)).all()
    assert {c.external_id for c in comments} == {"c-1", "c-2"}
    assert any(c.is_question for c in comments)
    # author handle is pseudonymised, never stored raw
    assert all(c.author_pseudonym != "UCfan1" for c in comments)
    # the sync stamps last_synced_at on the platform account
    from cci_core.models import PlatformAccount

    pa = session.scalar(select(PlatformAccount).where(
        PlatformAccount.creator_id == creator.id, PlatformAccount.platform == "youtube"))
    assert pa is not None and pa.last_synced_at is not None


def test_sync_native_is_idempotent(creator, session):
    from cci_workers.sync_native import sync_native

    sync_native(creator.id, "youtube", connector=_conn(), account=_account())
    stats2 = sync_native(creator.id, "youtube", connector=_conn(), account=_account())
    assert stats2["posts"] == 0 and stats2["comments"] == 0  # nothing new on re-run
    session.expire_all()
    posts = session.scalars(select(Post).where(
        Post.creator_id == creator.id, Post.platform == "youtube")).all()
    assert len(posts) == 2  # no duplicates
