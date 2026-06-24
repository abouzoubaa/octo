"""v2 agent features: engagement, intelligence, repurposing, revenue, brand."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from cci_agent.brand import detect_crisis, voice_consistency_score
from cci_agent.engagement import (
    bulk_approve,
    close_loop,
    defer_question,
    delegation_candidate,
    draft_reply,
    due_deferrals,
    handle_dm_followup,
)
from cci_agent.intelligence import (
    detect_trends,
    score_sentiment,
    segment_personas,
    sentiment_summary,
    strategy_advisor,
)
from cci_agent.repurposing import build_series, repurpose, sift_and_shift
from cci_agent.revenue import affiliate_optimisation, sponsor_report
from cci_core.agent_foundations import capture_voice, transition_demand
from cci_core.models import (
    Comment,
    DemandState,
    DemandTopic,
    DmJob,
    DmStatus,
    Post,
)
from cci_workers.radar import build_radar


def _radar(seeded_creator, session):
    build_radar(seeded_creator.id, backlog=True)
    session.expire_all()
    return session.scalars(
        select(DemandTopic).where(DemandTopic.creator_id == seeded_creator.id)).all()


# ----------------------------------------------------------------- engagement


def test_draft_reply_grounded_or_fallback(seeded_creator, session):
    reply = draft_reply(session, seeded_creator.id, seeded_creator.handle,
                        "how to handle price objections")
    assert reply["state"] in ("answered", "fallback")
    assert reply["deep_link"]


def test_draft_reply_low_confidence_falls_back(creator, session):
    reply = draft_reply(session, creator.id, creator.handle, "anything at all")
    assert reply["state"] == "fallback"
    assert reply["answer_id"] is None


def test_bulk_approve(seeded_creator, session):
    jobs = []
    for i in range(3):
        c = Comment(creator_id=seeded_creator.id, external_id=f"bulk-{i}",
                    author_pseudonym="x", text="q?", is_question=True)
        session.add(c)
        session.flush()
        j = DmJob(creator_id=seeded_creator.id, comment_id=c.id,
                  status=DmStatus.pending_approval, dm_text="hi")
        session.add(j)
        session.flush()
        jobs.append(j.id)
    assert bulk_approve(session, seeded_creator.id, jobs) == 3


def test_loop_closer_notifies_recent_askers(seeded_creator, session):
    now = datetime.now(timezone.utc)
    c = Comment(creator_id=seeded_creator.id, external_id="asker-1", author_pseudonym="fan",
                text="where's the post about X?", is_question=True, created_at=now - timedelta(days=1))
    session.add(c)
    session.flush()
    topic = DemandTopic(creator_id=seeded_creator.id, label="X explained", week="2026-W24",
                        asker_comment_ids=[c.id], state=DemandState.published)
    session.add(topic)
    session.flush()
    created = close_loop(session, topic, seeded_creator.handle)
    assert created == [c.id]
    assert topic.state == DemandState.loop_closed
    job = session.scalar(select(DmJob).where(DmJob.comment_id == c.id))
    assert job.status == DmStatus.pending_approval  # approval mode, never auto-send


def test_loop_closer_skips_stale_askers(seeded_creator, session):
    old = datetime.now(timezone.utc) - timedelta(days=30)
    c = Comment(creator_id=seeded_creator.id, external_id="asker-old", author_pseudonym="fan",
                text="old question", is_question=True, created_at=old)
    session.add(c)
    session.flush()
    topic = DemandTopic(creator_id=seeded_creator.id, label="Y", week="2026-W24",
                        asker_comment_ids=[c.id], state=DemandState.published)
    session.add(topic)
    session.flush()
    assert close_loop(session, topic, seeded_creator.handle) == []  # outside 7-day window


def test_defer_and_due(seeded_creator, session):
    item = defer_question(session, seeded_creator.id, "launch question", weeks=6)
    assert item.status == "waiting"
    assert due_deferrals(session, seeded_creator.id) == []  # not due yet
    item.remind_at = datetime.now(timezone.utc) - timedelta(days=1)
    session.flush()
    assert len(due_deferrals(session, seeded_creator.id)) == 1


def test_dm_followup_threads(seeded_creator, session):
    c = Comment(creator_id=seeded_creator.id, external_id="thread-c", author_pseudonym="fan",
                text="initial?", is_question=True)
    session.add(c)
    session.flush()
    parent = DmJob(creator_id=seeded_creator.id, comment_id=c.id, status=DmStatus.sent, turn=0)
    session.add(parent)
    session.flush()
    jid = handle_dm_followup(session, seeded_creator.id, seeded_creator.handle,
                             parent.id, "follow-up question")
    follow = session.get(DmJob, jid)
    assert follow.turn == 1 and follow.parent_job_id == parent.id
    assert follow.status == DmStatus.pending_approval


def test_delegation_candidate(seeded_creator, session):
    post = session.scalar(select(Post).where(Post.creator_id == seeded_creator.id))
    q = Comment(creator_id=seeded_creator.id, post_id=post.id, external_id="dq",
                author_pseudonym="a", text="how much protein should I eat daily for muscle",
                is_question=True)
    ans = Comment(creator_id=seeded_creator.id, post_id=post.id, external_id="da",
                  author_pseudonym="b",
                  text="you should eat about two grams of protein per kilo daily for muscle growth",
                  is_question=False)
    session.add_all([q, ans])
    session.flush()
    cand = delegation_candidate(session, seeded_creator.id, q)
    assert cand is not None and cand.id == ans.id


# ----------------------------------------------------------------- intelligence


def test_score_sentiment_markers():
    assert score_sentiment("I'm so worried I'll mess this up") == "anxiety"
    assert score_sentiment("this is amazing, love it 🔥") == "excitement"


def test_sentiment_summary(seeded_creator, session):
    summary = sentiment_summary(session, seeded_creator.id)
    assert "counts" in summary and "dominant" in summary


def test_segment_personas(seeded_creator, session):
    personas = segment_personas(session, seeded_creator.id, k=2)
    assert isinstance(personas, list)
    if personas:
        assert "persona" in personas[0] and personas[0]["size"] >= 2


def test_detect_trends_threshold(seeded_creator, session):
    t = DemandTopic(creator_id=seeded_creator.id, label="rising topic", week="2026-W24",
                    search_count=10, comment_count=10, wow_change=120.0,
                    coverage={"strength": 0.2})
    session.add(t)
    session.flush()
    trends = detect_trends(session, seeded_creator.id, threshold=3)
    assert any(tr["label"] == "rising topic" for tr in trends)


def test_strategy_advisor_grounded(seeded_creator, session):
    _radar(seeded_creator, session)
    out = strategy_advisor(session, seeded_creator.id, "should I expand into nutrition?")
    assert "recommendation" in out and "based_on" in out


# ----------------------------------------------------------------- repurposing


def test_repurpose_post(seeded_creator, session):
    post = session.scalar(select(Post).where(Post.creator_id == seeded_creator.id,
                                             Post.caption.isnot(None)))
    out = repurpose(session, post.id, "ig_carousel")
    assert out["format"] == "ig_carousel" and out["source_post_id"] == post.id


def test_build_series(seeded_creator, session):
    topic = _radar(seeded_creator, session)[0]
    series = build_series(session, seeded_creator.id, topic)
    assert "parts" in series and series["topic_id"] == topic.id


def test_sift_and_shift_handles_no_youtube(seeded_creator, session):
    assert sift_and_shift(session, seeded_creator.id) == []  # demo corpus is IG-only


# ----------------------------------------------------------------- revenue


def test_sponsor_report(seeded_creator, session):
    _radar(seeded_creator, session)
    report = sponsor_report(session, seeded_creator.id)
    assert "proof" in report and report["proof"]


def test_affiliate_optimisation_empty(seeded_creator, session):
    assert affiliate_optimisation(session, seeded_creator.id) == []  # no clicks yet


# ----------------------------------------------------------------- brand


def test_detect_crisis_no_spike(seeded_creator, session):
    result = detect_crisis(session, seeded_creator.id)
    assert "alert" in result


def test_voice_consistency_needs_voice_memory(seeded_creator, session):
    assert voice_consistency_score(session, seeded_creator.id, "hi")["score"] is None
    capture_voice(session, seeded_creator.id, "dm", "Hey friend! Here's the deal 💪")
    scored = voice_consistency_score(session, seeded_creator.id, "Hey friend! Here's the deal")
    assert "score" in scored


def test_published_to_loop_closed_via_transition(seeded_creator, session):
    t = DemandTopic(creator_id=seeded_creator.id, label="z", week="2026-W24",
                    state=DemandState.drafting)
    session.add(t)
    session.flush()
    transition_demand(session, t, DemandState.published, published_post_id="p1")
    assert t.state == DemandState.published
