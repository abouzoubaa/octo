"""GDPR/CCPA data subject rights: export and erasure.

Two kinds of subject:
- the CREATOR (account holder) — full export + full erasure (cascade).
- an AUDIENCE MEMBER — pseudonymous; export/erase by their per-creator pseudonym.

Audience data is already pseudonymised (no raw identities stored), so erasure
removes every row carrying the pseudonym.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cci_core.models import (
    Comment,
    Creator,
    DemandTopic,
    Offer,
    Outcome,
    Post,
    Product,
    Query,
    Subscription,
    VoiceExample,
    WaitlistEntry,
)


def export_creator_data(session: Session, creator_id: str) -> dict:
    """A portable JSON bundle of everything tied to a creator (Art. 20 portability)."""
    creator = session.get(Creator, creator_id)
    if creator is None:
        return {}

    def rows(model, **filters):
        stmt = select(model).filter_by(creator_id=creator_id, **filters)
        return [
            {c.key: _json_safe(getattr(r, c.key)) for c in model.__table__.columns}
            for r in session.scalars(stmt)
        ]

    sub = session.get(Subscription, creator_id)
    return {
        "creator": {c.key: _json_safe(getattr(creator, c.key))
                    for c in Creator.__table__.columns},
        "subscription": ({c.key: _json_safe(getattr(sub, c.key))
                          for c in Subscription.__table__.columns} if sub else None),
        "posts": rows(Post),
        "comments": rows(Comment),
        "queries": rows(Query),
        "demand_topics": rows(DemandTopic),
        "products": rows(Product),
        "offers": rows(Offer),
        "voice_examples": rows(VoiceExample),
        "outcomes": rows(Outcome),
        "note": "audience data is pseudonymous; no raw audience identities are stored",
    }


def delete_creator(session: Session, creator_id: str) -> bool:
    """Full erasure of a creator and all dependent rows (Art. 17).

    Uses a Core DELETE so the database's ON DELETE CASCADE foreign keys remove all
    children, rather than the ORM trying to NULL them. Expire the identity map so
    the deleted creator isn't served from cache afterwards.
    """
    creator = session.get(Creator, creator_id)
    if creator is None:
        return False
    session.expunge(creator)
    session.execute(delete(Creator).where(Creator.id == creator_id))
    session.expire_all()
    return True


def erase_audience_member(session: Session, creator_id: str, pseudonym: str) -> dict:
    """Erase one audience member's data within a creator, identified by pseudonym."""
    stats = {"comments": 0, "outcomes": 0}
    stats["comments"] = session.execute(
        delete(Comment).where(Comment.creator_id == creator_id,
                              Comment.author_pseudonym == pseudonym)
    ).rowcount
    stats["outcomes"] = session.execute(
        delete(Outcome).where(Outcome.creator_id == creator_id,
                              Outcome.asker_pseudonym == pseudonym)
    ).rowcount
    return stats


def forget_waitlist_email(session: Session, creator_id: str, email: str) -> int:
    """Erase a captured lead by email (waitlist is the one place we hold raw email)."""
    return session.execute(
        delete(WaitlistEntry).where(WaitlistEntry.creator_id == creator_id,
                                    WaitlistEntry.email == email)
    ).rowcount


def _json_safe(value):
    from datetime import datetime
    from enum import Enum

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value
