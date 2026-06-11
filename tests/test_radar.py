"""Demand Radar: clustering the comment backlog into evidence cards (cold start)."""
from sqlalchemy import select

from cci_core.models import DemandTopic
from cci_workers.radar import build_radar


def test_backlog_builds_evidence_cards(seeded_creator, session):
    n = build_radar(seeded_creator.id, backlog=True)
    assert n > 0
    cards = session.scalars(
        select(DemandTopic).where(DemandTopic.creator_id == seeded_creator.id)
    ).all()
    assert len(cards) == n
    top = max(cards, key=lambda c: c.search_count + c.comment_count)
    assert top.comment_count >= 1  # cold start runs on comments alone
    assert top.audience_language  # real verbatims, not paraphrase
    assert top.coverage is not None and "gap" in top.coverage


def test_radar_empty_creator(creator):
    assert build_radar(creator.id, backlog=True) == 0


def test_digest_renders(seeded_creator, session):
    build_radar(seeded_creator.id, backlog=True)
    from cci_workers.digest import render_digest

    digest = render_digest(seeded_creator.id)
    assert digest is not None
    assert "Demand Radar" in digest
    assert seeded_creator.handle in digest
