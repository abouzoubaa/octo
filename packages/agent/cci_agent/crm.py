"""Customer CRM (v3): unified audience profiles + lifecycle segments.

For creators with paid products. Profiles are built from pseudonymous audience
activity (comments, searches, waitlist) — never raw identities; aggregate by the
per-creator pseudonym only. Lifecycle marketing drives milestone/re-engagement.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.models import Comment, WaitlistEntry


def customer_profiles(session: Session, creator_id: str, limit: int = 50) -> list[dict]:
    """Unify a fan's activity by their per-creator pseudonym into one profile."""
    comments = session.scalars(
        select(Comment).where(Comment.creator_id == creator_id)
    ).all()
    profiles: dict[str, dict] = {}
    for c in comments:
        p = profiles.setdefault(c.author_pseudonym, {
            "pseudonym": c.author_pseudonym, "questions": 0, "comments": 0,
            "first_seen": c.created_at, "last_seen": c.created_at, "topics": []})
        p["comments"] += 1
        if c.is_question:
            p["questions"] += 1
        if c.created_at:
            if p["first_seen"] is None or c.created_at < p["first_seen"]:
                p["first_seen"] = c.created_at
            if p["last_seen"] is None or c.created_at > p["last_seen"]:
                p["last_seen"] = c.created_at

    out = []
    for p in profiles.values():
        out.append({
            "pseudonym": p["pseudonym"],
            "questions": p["questions"], "comments": p["comments"],
            "engagement": "high" if p["comments"] >= 3 else "low",
            "first_seen": p["first_seen"].isoformat() if p["first_seen"] else None,
            "last_seen": p["last_seen"].isoformat() if p["last_seen"] else None,
        })
    out.sort(key=lambda x: x["comments"], reverse=True)
    return out[:limit]


def lifecycle_segments(session: Session, creator_id: str) -> dict:
    """Bucket the audience for lifecycle marketing: new, engaged, dormant, leads."""
    now = datetime.now(timezone.utc)
    dormant_cutoff = now - timedelta(days=30)
    profiles = customer_profiles(session, creator_id, limit=10_000)

    segments = {"engaged": [], "dormant": [], "new": []}
    for p in profiles:
        last = datetime.fromisoformat(p["last_seen"]) if p["last_seen"] else None
        if p["comments"] >= 3 and last and last >= dormant_cutoff:
            segments["engaged"].append(p["pseudonym"])
        elif last and last < dormant_cutoff:
            segments["dormant"].append(p["pseudonym"])
        else:
            segments["new"].append(p["pseudonym"])

    leads = session.scalars(
        select(WaitlistEntry).where(WaitlistEntry.creator_id == creator_id,
                                    WaitlistEntry.notified.is_(False))
    ).all()
    return {
        "engaged": len(segments["engaged"]),
        "dormant": len(segments["dormant"]),
        "new": len(segments["new"]),
        "waitlist_leads": len(leads),
        "actions": {
            "dormant": "30-day re-engagement message" if segments["dormant"] else None,
            "leads": "notify when their topic is covered" if leads else None,
        },
    }
