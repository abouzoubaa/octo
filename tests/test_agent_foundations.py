"""Agent-layer foundations: state machine, outcome log, voice memory, offers, rules."""
import pytest

from cci_core.agent_foundations import (
    InvalidTransition,
    active_offers,
    best_offer_for_topics,
    capture_voice,
    get_rules,
    is_taboo,
    must_escalate,
    record_outcome,
    transition_demand,
    voice_prompt_block,
    voice_samples,
)
from cci_core.models import DemandState, DemandTopic, Offer, Outcome


def _topic(session, creator_id, label="High-protein breakfast"):
    t = DemandTopic(creator_id=creator_id, label=label, week="2026-W24")
    session.add(t)
    session.flush()
    return t


# ----------------------------------------------------------- state machine


def test_demand_starts_new(seeded_creator, session):
    t = _topic(session, seeded_creator.id)
    assert t.state == DemandState.new


def test_valid_transition_chain(seeded_creator, session):
    t = _topic(session, seeded_creator.id)
    transition_demand(session, t, DemandState.idea)
    transition_demand(session, t, DemandState.drafting)
    transition_demand(session, t, DemandState.published, published_post_id="post-1")
    transition_demand(session, t, DemandState.loop_closed)
    assert t.state == DemandState.loop_closed
    assert t.published_post_id == "post-1"
    assert t.creator_marked == "made"  # legacy field kept consistent


def test_invalid_transition_rejected(seeded_creator, session):
    t = _topic(session, seeded_creator.id)
    with pytest.raises(InvalidTransition):
        transition_demand(session, t, DemandState.published)  # new → published not allowed


def test_dismiss_and_revive(seeded_creator, session):
    t = _topic(session, seeded_creator.id)
    transition_demand(session, t, DemandState.dismissed)
    assert t.creator_marked == "not"
    transition_demand(session, t, DemandState.idea)  # dismissed → idea allowed
    assert t.state == DemandState.idea


# --------------------------------------------------------------- outcome log


def test_record_and_advance_outcome(seeded_creator, session):
    o = record_outcome(session, seeded_creator.id, source="search",
                       question_text="how to lose fat", served_state="answered", confidence=0.7)
    assert o.stage == "served"
    from cci_core.agent_foundations import advance_outcome

    advance_outcome(session, o.id, stage="clicked", result={"clicked": True})
    refreshed = session.get(Outcome, o.id)
    assert refreshed.stage == "clicked"
    assert refreshed.result["clicked"] is True


# --------------------------------------------------------------- voice memory


def test_capture_and_render_voice(seeded_creator, session):
    capture_voice(session, seeded_creator.id, "dm", "Hey! Here's the exact routine 💪",
                  source="approved")
    capture_voice(session, seeded_creator.id, "hook", "What can I eat that isn't eggs?")
    assert len(voice_samples(session, seeded_creator.id)) == 2
    assert len(voice_samples(session, seeded_creator.id, kind="dm")) == 1
    block = voice_prompt_block(session, seeded_creator.id, kind="dm")
    assert "exact routine" in block
    assert voice_prompt_block(session, "nonexistent") == ""  # empty when nothing learned


# --------------------------------------------------------------------- offers


def test_active_offers_priority_and_window(seeded_creator, session):
    session.add(Offer(creator_id=seeded_creator.id, name="Course", kind="course",
                      topics=["fat loss"], priority=5, active=True))
    session.add(Offer(creator_id=seeded_creator.id, name="Old launch", kind="launch",
                      priority=9, active=False))
    session.flush()
    offers = active_offers(session, seeded_creator.id)
    assert [o.name for o in offers] == ["Course"]  # inactive excluded


def test_best_offer_matches_topic(seeded_creator, session):
    session.add(Offer(creator_id=seeded_creator.id, name="Protein guide", kind="product",
                      topics=["protein", "breakfast"], priority=1, active=True))
    session.add(Offer(creator_id=seeded_creator.id, name="Generic", kind="newsletter",
                      topics=[], priority=0, active=True))
    session.flush()
    best = best_offer_for_topics(session, seeded_creator.id, ["breakfast"])
    assert best.name == "Protein guide"


# ----------------------------------------------------------- rules & preferences


def test_rules_lazy_create_and_guards(seeded_creator, session):
    rules = get_rules(session, seeded_creator.id)
    rules.taboo_topics = ["medical diagnosis"]
    rules.escalate_topics = ["refund"]
    session.flush()
    assert is_taboo(rules, "can you give me a medical diagnosis?")
    assert not is_taboo(rules, "what's a good breakfast?")
    assert must_escalate(rules, "I want a refund please")
