"""Review fixes for the cross-platform waves (L-O): capability enforcement,
canonical idempotency, import error path, migration sync."""
from sqlalchemy import select

from cci_core.models import Comment, DmJob, DmStatus, OAuthToken, Post


class _FakeIG:
    def __init__(self, *a, **k):
        self.sent = []

    def reply_to_comment(self, cid, msg):
        self.sent.append(("reply", cid))

    def private_reply(self, cid, msg):
        self.sent.append(("dm", cid))


def _approved_job_on(session, creator, platform, external):
    post = Post(creator_id=creator.id, platform=platform, external_id=f"p-{external}", type="video")
    session.add(post)
    session.flush()
    c = Comment(creator_id=creator.id, post_id=post.id, external_id=external,
                author_pseudonym="a", text="q?", is_question=True)
    session.add(c)
    session.flush()
    j = DmJob(creator_id=creator.id, comment_id=c.id, status=DmStatus.approved, dm_text="hi")
    session.add(j)
    session.add(OAuthToken(creator_id=creator.id, platform="instagram", access_token="t"))
    session.commit()
    return j


# ----------------------------------------------------- capability enforcement (#5)


def test_dispatch_blocks_archive_only_platform(seeded_creator, session, monkeypatch):
    """A TikTok (archive: no comment/message capability) job must NOT be sent."""
    from cci_workers import dm

    job = _approved_job_on(session, seeded_creator, "tiktok", "tt-job")
    monkeypatch.setattr("cci_core.instagram.InstagramClient", _FakeIG)
    stats = dm.dispatch_approved(seeded_creator.id)
    assert stats["sent"] == 0 and stats["failed"] == 1
    session.expire_all()
    refreshed = session.get(DmJob, job.id)
    assert refreshed.status == DmStatus.failed
    assert "capability" in refreshed.error


def test_dispatch_allows_instagram(seeded_creator, session, monkeypatch):
    from cci_workers import dm

    _approved_job_on(session, seeded_creator, "instagram", "ig-job")
    monkeypatch.setattr("cci_core.instagram.InstagramClient", _FakeIG)
    stats = dm.dispatch_approved(seeded_creator.id)
    assert stats["sent"] == 1  # IG has comment-reply + messaging


def test_can_dm_capability_helper():
    from cci_workers.dm import _can_dm

    assert _can_dm("instagram") is True
    assert _can_dm("tiktok") is False  # archive default
    assert _can_dm("youtube") is False  # no DM surface
    assert _can_dm("newsletter") is False  # demand source, no actions


# ----------------------------------------------------- canonical idempotency (#1)


def test_group_variants_no_orphans_on_rerun(creator, session):
    from cci_agent.canonical import group_variants
    from cci_core.models import CanonicalContent

    for i in range(3):
        session.add(Post(creator_id=creator.id, platform="tiktok", external_id=f"c{i}",
                         type="video", caption=f"distinct topic number {i} about travel hacks"))
    session.flush()
    group_variants(session, creator.id)
    n_after_first = session.scalar(select(CanonicalContent.id).where(
        CanonicalContent.creator_id == creator.id))
    assert n_after_first is not None
    # rerun twice — canonical count stays stable, no orphan accumulation
    group_variants(session, creator.id)
    group_variants(session, creator.id)
    total = len(session.scalars(select(CanonicalContent).where(
        CanonicalContent.creator_id == creator.id)).all())
    n_posts = len(session.scalars(select(Post).where(Post.creator_id == creator.id)).all())
    assert total <= n_posts  # never more canonicals than posts


# ----------------------------------------------------- import error path (#3)


def test_import_missing_external_id_is_422(creator):
    import pytest as _pytest

    from cci_workers.ingest_import import ingest_imported

    with _pytest.raises(ValueError):  # not KeyError → endpoint maps to 422
        ingest_imported(creator.id, "tiktok", [{"caption": "no id here"}])


# ----------------------------------------------------- migration sync (#7)


def test_post_migration_columns_present(session):
    """The columns radar/canonical write must exist (current schema)."""
    from sqlalchemy import text

    for col in ("canonical_id", "language", "impressions"):
        present = session.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='posts' AND column_name=:c"), {"c": col}).first()
        assert present is not None, f"posts.{col} missing"
    for col in ("source_breakdown", "demand_segment", "manipulation_risk"):
        present = session.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='demand_topics' AND column_name=:c"), {"c": col}).first()
        assert present is not None, f"demand_topics.{col} missing"


def test_add_column_if_not_exists_is_idempotent(session):
    """The migration's ADD COLUMN IF NOT EXISTS pattern is safe on an existing column."""
    from sqlalchemy import text

    # re-adding an existing column must be a no-op, not an error
    session.execute(text(
        'ALTER TABLE posts ADD COLUMN IF NOT EXISTS "language" VARCHAR(8)'))
    session.execute(text(
        'ALTER TABLE demand_topics ADD COLUMN IF NOT EXISTS "demand_segment" VARCHAR(24)'))
    session.commit()  # no exception = idempotent
