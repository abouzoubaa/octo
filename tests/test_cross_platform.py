"""Wave N: TikTok connector levels, import ingestion, per-platform demand, Sift & Shift."""
from sqlalchemy import select

from cci_agent.canonical import group_variants
from cci_agent.demand import _demand_segmentation
from cci_agent.repurposing import draft_shift, sift_and_shift_opportunities
from cci_core.connectors import capabilities_for, get_connector
from cci_core.connectors.base import COMMENTS_READ, CONTENT_READ, MESSAGES_SEND
from cci_core.connectors.tiktok import TikTokConnector
from cci_core.models import Comment, Post, Transcript
from cci_workers.ingest_import import ingest_imported


# ----------------------------------------------------------- TikTok connector levels


def test_tiktok_archive_has_no_comments():
    archive = TikTokConnector(full_loop=False)
    caps = archive.capabilities()
    assert CONTENT_READ in caps
    assert COMMENTS_READ not in caps  # archive level: no comment dependency
    assert MESSAGES_SEND not in caps


def test_tiktok_full_loop_unlocks_comments():
    full = TikTokConnector(full_loop=True)
    caps = full.capabilities()
    assert {COMMENTS_READ, MESSAGES_SEND} <= caps


def test_tiktok_registered_default_archive():
    assert "tiktok" in [get_connector("tiktok").platform]
    assert COMMENTS_READ not in capabilities_for("tiktok")  # default = archive


# ----------------------------------------------------------- import ingestion


def test_import_creates_posts_and_transcripts(creator, session):
    items = [
        {"external_id": "tt-1", "kind": "video",
         "caption": "budget tokyo tips", "transcript": "capsule hotel, 7-eleven breakfast"},
        {"external_id": "tt-2", "kind": "video", "caption": "cheap flights"},
    ]
    stats = ingest_imported(creator.id, "tiktok", items)
    assert stats["posts"] == 2 and stats["transcripts"] == 1
    session.expire_all()
    posts = session.scalars(select(Post).where(Post.creator_id == creator.id,
                                               Post.platform == "tiktok")).all()
    assert len(posts) == 2
    # idempotent re-import
    assert ingest_imported(creator.id, "tiktok", items)["posts"] == 0


def test_import_creates_archive_platform_account(creator, session):
    ingest_imported(creator.id, "tiktok", [{"external_id": "tt-x", "caption": "hi there"}])
    from cci_core.models import PlatformAccount

    session.expire_all()
    acct = session.scalar(select(PlatformAccount).where(
        PlatformAccount.creator_id == creator.id, PlatformAccount.platform == "tiktok"))
    assert acct.status == "archive_only" and acct.mode == "import"


def test_import_rejects_unknown_platform(creator, session):
    import pytest

    with pytest.raises(ValueError):
        ingest_imported(creator.id, "myspace", [{"external_id": "x"}])


# ----------------------------------------------------------- per-platform demand


def test_demand_segment_everywhere(seeded_creator, session):
    ig = Post(creator_id=seeded_creator.id, platform="instagram", external_id="p-ig", type="reel")
    tt = Post(creator_id=seeded_creator.id, platform="tiktok", external_id="p-tt", type="video")
    session.add_all([ig, tt])
    session.flush()
    comments = [
        Comment(creator_id=seeded_creator.id, post_id=ig.id, external_id="c1",
                author_pseudonym="a", text="q?", is_question=True),
        Comment(creator_id=seeded_creator.id, post_id=tt.id, external_id="c2",
                author_pseudonym="b", text="q?", is_question=True),
    ]
    session.add_all(comments)
    session.flush()
    breakdown, segment = _demand_segmentation(session, comments, n_searches=3)
    assert segment == "everywhere"  # asked on 2 platforms
    assert breakdown["instagram"] == 1 and breakdown["tiktok"] == 1 and breakdown["search"] == 3


def test_demand_segment_search_only(seeded_creator, session):
    breakdown, segment = _demand_segmentation(session, [], n_searches=5)
    assert segment == "search_only" and breakdown == {"search": 5}


# ----------------------------------------------------------- Sift & Shift


def test_sift_and_shift_finds_missing_platform(creator, session):
    # an answer on YouTube but not TikTok, with demand → a migration opportunity
    yt = Post(creator_id=creator.id, platform="youtube", external_id="yt-ss",
              type="video", caption="how to choose a travel esim for international trips")
    session.add(yt)
    session.flush()
    session.add(Transcript(post_id=yt.id, source="whisper",
                           text="pick an esim with regional coverage and check the data caps"))
    from cci_core.models import DemandTopic

    session.add(DemandTopic(creator_id=creator.id, label="travel esim", week="2026-W24",
                            search_count=8, comment_count=4))
    session.flush()
    group_variants(session, creator.id)

    opps = sift_and_shift_opportunities(session, creator.id, target_platform="tiktok")
    assert opps
    o = opps[0]
    assert o["source_platform"] == "youtube" and o["target_platform"] == "tiktok"
    assert o["has_demand"] is True

    # and we can draft the platform-native version from the source
    draft = draft_shift(session, o["source_post_id"], "tiktok")
    assert draft["target_platform"] == "tiktok" and draft["migrated"] is True
    # the migrated draft is persisted into the creator's Drafts (actionable, editable)
    from cci_core.models import ContentDraft

    assert draft["draft_id"]
    saved = session.get(ContentDraft, draft["draft_id"])
    assert saved is not None and saved.creator_id == creator.id
    assert saved.source_post_ids == [o["source_post_id"]]
    assert saved.brief["target_platform"] == "tiktok"


def test_sift_and_shift_skips_already_covered(creator, session):
    # an answer already on TikTok → not an opportunity to shift TO TikTok
    tt = Post(creator_id=creator.id, platform="tiktok", external_id="tt-cov",
              type="video", caption="packing cubes carry on only three weeks")
    session.add(tt)
    session.flush()
    group_variants(session, creator.id)
    opps = sift_and_shift_opportunities(session, creator.id, target_platform="tiktok")
    assert all(o["source_platform"] != "tiktok" for o in opps)
