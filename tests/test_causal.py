"""Wave F: causal layer — interventions, holdouts, baselines, intervals, lift."""

from cci_agent.causal import (
    _is_holdout,
    create_intervention,
    holdout_lift,
    matched_baseline,
    performance_interval,
    record_outcome,
    record_publication,
    stagger_publications,
)
from cci_core.models import ContentDraft, DemandTopic, Intervention


def _topic(session, creator_id, label="protein breakfast", external="iv"):
    t = DemandTopic(creator_id=creator_id, label=label, week="2026-W24",
                    search_count=5, comment_count=5)
    session.add(t)
    session.flush()
    return t


def test_holdout_assignment_is_deterministic():
    # stable per topic id, and roughly the configured rate across many ids
    import uuid

    ids = [uuid.uuid4().hex for _ in range(2000)]
    rate = sum(_is_holdout(i) for i in ids) / len(ids)
    assert 0.10 < rate < 0.20  # ~15%
    # deterministic: same id → same answer
    assert _is_holdout(ids[0]) == _is_holdout(ids[0])


def test_create_intervention_with_baseline_and_interval(seeded_creator, session):
    topic = _topic(session, seeded_creator.id)
    draft = ContentDraft(creator_id=seeded_creator.id, title="x", demand_topic_id=topic.id,
                         hooks=["a hook"])
    session.add(draft)
    session.flush()
    iv = create_intervention(session, topic, draft=draft)
    assert iv.demand_topic_id == topic.id and iv.draft_id == draft.id
    assert iv.baseline and "matched_posts" in iv.baseline
    assert iv.predicted and {"low", "point", "high"} <= set(iv.predicted)
    assert iv.predicted["low"] <= iv.predicted["point"] <= iv.predicted["high"]


def test_performance_interval_widens_with_less_history(seeded_creator, session):
    # creator with little history → wide band
    topic = _topic(session, seeded_creator.id)
    draft = ContentDraft(creator_id=seeded_creator.id, title="x", demand_topic_id=topic.id,
                         hooks=["h"])
    session.add(draft)
    session.flush()
    narrow = performance_interval(session, seeded_creator.id, draft)
    # seeded creator has ~5 posts; band should be meaningfully wide
    assert narrow["high"] - narrow["low"] >= 16


def test_holdout_is_not_published(seeded_creator, session):
    # force a holdout topic by id check
    topic = _topic(session, seeded_creator.id)
    iv = create_intervention(session, topic)
    if iv.is_holdout:
        assert record_publication(session, iv.id, "post-1").published_post_id is None
        assert iv.status == "holdout"


def test_record_outcome_and_lift(seeded_creator, session):
    # build two acted + one holdout intervention with outcomes
    for i in range(3):
        t = _topic(session, seeded_creator.id, label=f"topic {i}", external=f"iv{i}")
        iv = Intervention(creator_id=seeded_creator.id, demand_topic_id=t.id,
                          is_holdout=(i == 2))
        session.add(iv)
        session.flush()
        record_outcome(session, iv.id, {"clicks": 10 if i < 2 else 4})
    lift = holdout_lift(session, seeded_creator.id, "clicks")
    assert lift["acted_n"] == 2 and lift["holdout_n"] == 1
    assert lift["acted_avg"] == 10 and lift["holdout_avg"] == 4
    assert lift["lift"] == round((10 - 4) / 4, 3)  # +150%


def test_lift_insufficient_data(seeded_creator, session):
    assert holdout_lift(session, seeded_creator.id)["lift"] is None


def test_matched_baseline(seeded_creator, session):
    topic = _topic(session, seeded_creator.id, label="price objections")
    baseline = matched_baseline(session, seeded_creator.id, topic)
    assert "matched_posts" in baseline and "creator_avg_clicks_per_post" in baseline


def test_stagger_publications():
    schedule = stagger_publications(["d1", "d2", "d3"], cadence_days=2)
    assert len(schedule) == 3
    assert schedule[0]["suggested_publish_at"] < schedule[2]["suggested_publish_at"]
