"""Wave D: trust-calibrated permission ladder + briefing originality mix."""
import pytest

from cci_agent.permissions import (
    can_auto_execute,
    pause_automation,
    permission_for,
    permission_summary,
    set_permission,
)


# ----------------------------------------------------------- permission ladder


def test_default_levels_are_conservative(seeded_creator, session):
    # high-risk actions default low; nothing auto-executes by default
    assert permission_for(session, seeded_creator.id, "public_comment_reply") == "recommend"
    assert permission_for(session, seeded_creator.id, "dm_reply") == "draft"
    assert not can_auto_execute(session, seeded_creator.id, "dm_reply")


def test_risk_ceiling_clamps_high_risk_actions(seeded_creator, session):
    # dm_reply's ceiling is 'batch' — requesting 'auto' is clamped
    effective = set_permission(session, seeded_creator.id, "dm_reply", "auto")
    assert effective == "batch"
    assert not can_auto_execute(session, seeded_creator.id, "dm_reply")


def test_low_risk_action_can_reach_auto(seeded_creator, session):
    effective = set_permission(session, seeded_creator.id, "affiliate_inject", "auto")
    assert effective == "auto"
    assert can_auto_execute(session, seeded_creator.id, "affiliate_inject")


def test_pause_blocks_all_auto_execution(seeded_creator, session):
    set_permission(session, seeded_creator.id, "affiliate_inject", "auto")
    assert can_auto_execute(session, seeded_creator.id, "affiliate_inject")
    pause_automation(session, seeded_creator.id, paused=True)  # anomaly kill-switch
    assert not can_auto_execute(session, seeded_creator.id, "affiliate_inject")


def test_can_auto_approve_dm_requires_ladder(seeded_creator, session):
    from cci_agent.engagement import can_auto_approve
    from cci_core.agent_foundations import get_rules

    rules = get_rules(session, seeded_creator.id)
    rules.auto_approve_types = ["question"]
    session.flush()
    # opted in by intent, but dm_reply caps at 'batch' → still NOT auto
    assert can_auto_approve(session, seeded_creator.id, "question") is False


def test_invalid_permission_rejected(seeded_creator, session):
    with pytest.raises(ValueError):
        set_permission(session, seeded_creator.id, "dm_reply", "nonsense")
    with pytest.raises(ValueError):
        set_permission(session, seeded_creator.id, "unknown_action", "auto")


def test_permission_summary_shape(seeded_creator, session):
    summary = permission_summary(session, seeded_creator.id)
    assert "automation_paused" in summary
    assert "dm_reply" in summary["actions"]
    assert summary["actions"]["dm_reply"]["ceiling"] == "batch"


# ----------------------------------------------------------- briefing originality


def test_briefing_includes_originality_mix(seeded_creator, session):
    from cci_workers.enrich import process_all_pending
    from cci_workers.radar import build_radar

    process_all_pending(seeded_creator.id)  # create enrichment topics
    build_radar(seeded_creator.id, backlog=True)
    session.expire_all()
    from cci_agent.briefing import build_briefing

    briefing = build_briefing(session, seeded_creator.id, with_draft=False)
    assert briefing is not None
    assert "originality" in briefing
    assert briefing["originality"]["conviction_prompt"]  # always present
    # adjacent_exploration may be None if all topics are in demand — key still exists
    assert "adjacent_exploration" in briefing["originality"]
