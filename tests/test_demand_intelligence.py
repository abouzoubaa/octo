"""Wave A: Demand Integrity, explainable Opportunity Score, north-star metric."""
from datetime import timedelta

from sqlalchemy import select

from cci_agent.demand import closed_loops, compute_integrity, opportunity_score, score_topic
from cci_core.agent_foundations import transition_demand, utcnow
from cci_core.models import Comment, DemandState, DemandTopic
from cci_workers.radar import build_radar


def _radar(creator, session):
    build_radar(creator.id, backlog=True)
    session.expire_all()
    return session.scalars(
        select(DemandTopic).where(DemandTopic.creator_id == creator.id)).all()


# ----------------------------------------------------------- Demand Integrity


def test_integrity_counts_unique_askers_and_prompted(seeded_creator, session):
    # two comments from the SAME pseudonym + one CTA-style 'PLAN' single token
    c1 = Comment(creator_id=seeded_creator.id, external_id="i1", author_pseudonym="fanA",
                 text="how do I structure a push day workout?", is_question=True)
    c2 = Comment(creator_id=seeded_creator.id, external_id="i2", author_pseudonym="fanA",
                 text="and what about pull day?", is_question=True)
    c3 = Comment(creator_id=seeded_creator.id, external_id="i3", author_pseudonym="fanB",
                 text="PLAN", is_question=False)
    session.add_all([c1, c2, c3])
    session.flush()
    cluster = [("comment", c1.text, c1.id), ("comment", c2.text, c2.id),
               ("comment", c3.text, c3.id)]
    integ = compute_integrity(session, seeded_creator.id, cluster, "push day", "2026-W24")
    assert integ["unique_askers"] == 2  # fanA deduped
    assert integ["prompted_count"] == 1  # 'PLAN' single token
    assert integ["organic_count"] == 2
    assert integ["persistence_weeks"] == 1


def test_opportunity_score_components_exposed(seeded_creator, session):
    result = opportunity_score(
        session, seeded_creator.id, volume=20, velocity_pct=100.0, persistence_weeks=4,
        coverage_strength=0.1, intent_class="purchase", has_offer=True,
        dominant_sentiment="confusion", coverage={"post_ids": []})
    assert 0 <= result["score"] <= 100
    comps = result["components"]
    assert comps["demand_volume"] == 1.0  # 20+ volume saturates
    assert comps["coverage_gap"] > 0.8  # weak coverage = opportunity
    assert comps["commercial_intent"] == 1.0  # purchase intent
    assert "fatigue_penalty" in comps


def test_opportunity_score_penalises_saturation(seeded_creator, session):
    # a strongly-covered, recently-posted topic scores lower than an open gap
    topics = _radar(seeded_creator, session)
    assert topics
    scored = [score_topic(session, t) for t in topics]
    assert all(0 <= s["score"] <= 100 for s in scored)


def test_radar_populates_integrity_and_score(seeded_creator, session):
    topics = _radar(seeded_creator, session)
    assert topics
    t = topics[0]
    assert t.opportunity_score is not None
    assert t.opportunity_components and "demand_volume" in t.opportunity_components
    assert t.unique_askers >= 1
    assert t.intent_class in ("purchase", "learning", "support", "other")


# ----------------------------------------------------------- north-star metric


def test_closed_loops_counts_only_closed(seeded_creator, session):
    # build two topics; close one
    t1 = DemandTopic(creator_id=seeded_creator.id, label="a", week="2026-W24",
                     state=DemandState.published)
    t2 = DemandTopic(creator_id=seeded_creator.id, label="b", week="2026-W24",
                     state=DemandState.drafting)
    session.add_all([t1, t2])
    session.flush()
    transition_demand(session, t1, DemandState.loop_closed)
    session.flush()
    ns = closed_loops(session, seeded_creator.id, weeks=8)
    assert ns["closed_loops"] == 1
    assert ns["in_flight_loops"] >= 1  # t2 still drafting
    assert ns["closed_loops_per_week"] == round(1 / 8, 2)


def test_repromote_closes_loop_and_logs_outcome(seeded_creator, session):
    from cci_agent.demand import repromote_topic
    from cci_core.models import Outcome

    # a well-covered topic (the answer already exists) in an early state
    t = DemandTopic(creator_id=seeded_creator.id, label="esim guide", week="2026-W24",
                    state=DemandState.new, search_count=9,
                    coverage={"strength": 0.8, "permalinks": ["https://x/p1"]})
    session.add(t)
    session.flush()

    res = repromote_topic(session, t)
    assert res["closed"] is True and res["state"] == "loop_closed"
    assert res["permalink"] == "https://x/p1"
    session.flush()

    # the loop now counts toward the north-star metric
    assert closed_loops(session, seeded_creator.id, weeks=8)["closed_loops"] >= 1
    # an Outcome was logged with the re-promote action
    o = session.get(Outcome, res["outcome_id"])
    assert o.creator_action == "repromote" and o.stage == "closed"
    assert o.demand_topic_id == t.id

    # idempotent-ish: re-promoting an already-closed topic doesn't re-close it
    res2 = repromote_topic(session, t)
    assert res2["closed"] is False  # already closed, no double-count


def test_closed_loops_window_excludes_old(seeded_creator, session):
    t = DemandTopic(creator_id=seeded_creator.id, label="old", week="2026-W01",
                    state=DemandState.published)
    session.add(t)
    session.flush()
    transition_demand(session, t, DemandState.loop_closed)
    t.state_updated_at = utcnow() - timedelta(weeks=20)  # outside the window
    session.flush()
    assert closed_loops(session, seeded_creator.id, weeks=8)["closed_loops"] == 0
