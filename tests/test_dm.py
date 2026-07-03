"""Comment-to-DM: approval mode, one-reply-per-comment, fallback behaviour."""
from sqlalchemy import select

from cci_core.models import DmJob, DmStatus
from cci_workers.dm import handle_comment_event


def test_question_comment_creates_pending_job(seeded_creator, session):
    job_id = handle_comment_event(
        seeded_creator.id, "wh-1", "where's the reel about price objections?",
        "fan-123", media_external_id="demo-1",
    )
    assert job_id is not None
    job = session.get(DmJob, job_id)
    assert job.status == DmStatus.pending_approval  # approval mode first — always
    assert job.deep_link and seeded_creator.handle in job.deep_link
    assert job.dm_text and "http" in job.dm_text  # the first DM carries the value


def test_duplicate_comment_never_gets_second_reply(seeded_creator, session):
    first = handle_comment_event(seeded_creator.id, "wh-2", "how much protein?", "fan-1", None)
    second = handle_comment_event(seeded_creator.id, "wh-2", "how much protein?", "fan-1", None)
    assert first is not None
    assert second is None  # platform rule: one private reply per comment


def test_noise_comment_creates_no_job(seeded_creator, session):
    job_id = handle_comment_event(seeded_creator.id, "wh-3", "🔥🔥🔥", "fan-9", None)
    assert job_id is None
    jobs = session.scalars(select(DmJob).where(DmJob.creator_id == seeded_creator.id)).all()
    assert all(j.comment_id for j in jobs)


def test_low_confidence_falls_back_to_archive_link(creator, session):
    # empty corpus → retrieval confidence 0 → archive-link fallback, never a shaky answer
    job_id = handle_comment_event(creator.id, "wh-4", "what supplements do you take?", "fan-2", None)
    assert job_id is not None
    job = session.get(DmJob, job_id)
    assert "search everything" in job.dm_text.lower() or creator.handle in job.dm_text
    assert job.answer_id is None
