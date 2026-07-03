"""Public developer API (v3 · scale): read-only access to a creator's demand
intelligence, authenticated by an API key. The foundation for a dev ecosystem.

Scoped + revocable keys; aggregate/pseudonymous data only — same privacy posture
as the rest of Sift.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_agent.team import verify_api_key
from cci_core.db import get_db
from cci_core.models import ApiKey, DemandTopic

router = APIRouter(prefix="/v1/public", tags=["public-api"])


def require_api_key(authorization: str = Header(default=""),
                    db: Session = Depends(get_db)) -> ApiKey:
    key = authorization.removeprefix("Bearer ").strip()
    record = verify_api_key(db, key)
    if record is None:
        raise HTTPException(status_code=401, detail="invalid or revoked API key")
    return record


def _scoped(record: ApiKey, scope: str) -> None:
    # fail closed: a key with no scopes grants nothing (not everything)
    if not record.scopes or scope not in record.scopes:
        raise HTTPException(status_code=403, detail=f"key missing scope '{scope}'")


@router.get("/demand")
def demand(week: str | None = None, key: ApiKey = Depends(require_api_key),
           db: Session = Depends(get_db)) -> list[dict]:
    """Top demand topics for the key's creator (scope: demand:read)."""
    _scoped(key, "demand:read")
    stmt = select(DemandTopic).where(DemandTopic.creator_id == key.creator_id)
    if week:
        stmt = stmt.where(DemandTopic.week == week)
    rows = db.scalars(stmt.order_by(
        (DemandTopic.search_count + DemandTopic.comment_count).desc()).limit(50)).all()
    return [{"label": t.label, "searches": t.search_count, "comments": t.comment_count,
             "wow_change": t.wow_change, "state": t.state.value,
             "coverage_gap": (t.coverage or {}).get("gap")} for t in rows]


@router.get("/answer")
def canonical_answer(q: str = Query(..., min_length=1, max_length=500),
                     key: ApiKey = Depends(require_api_key),
                     db: Session = Depends(get_db)) -> dict:
    """Creator-authorized knowledge endpoint (scope: answer:read).

    A grounded, cited answer from the creator's archive — for external assistants,
    sites, and tools to use the creator as their authorized knowledge layer. Returns
    the answer, exact citations, the relevant current offer, and a canonical URL.
    Same grounding guarantees as the fan page: low confidence → no answer, not a guess.
    """
    _scoped(key, "answer:read")
    from cci_agent.monetization import offer_cta
    from cci_core.deep_links import answer_link, search_link
    from cci_core.models import Creator
    from cci_retrieval.answer import generate_answer, persist_answer

    creator = db.get(Creator, key.creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="creator not found")

    card = generate_answer(db, creator.id, q, op="api_answer")
    if card.state != "answered":
        return {"state": "no_answer", "canonical_url": search_link(creator.handle, q),
                "note": "no strong answer in the creator's archive"}
    answer = persist_answer(db, creator.id, card)
    topics = [c.get("topic") for c in card.citations if c.get("topic")]
    return {
        "state": "answered",
        "answer": card.text,
        "citations": card.citations,
        "offer": offer_cta(db, creator.id, topics or [q]),
        "canonical_url": answer_link(creator.handle, q, answer.id),
        "confidence": round(card.confidence, 3),
    }
