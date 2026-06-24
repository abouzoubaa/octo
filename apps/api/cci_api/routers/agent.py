"""Agent-layer API: demand-item state machine, voice memory, offers, rules, outcomes.

The shared foundations the proactive Sift features (Briefing, draft generator,
agentic DM, Loop-Closer, …) call into. Operator/creator-authenticated.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_api.deps import require_admin
from cci_core.agent_foundations import (
    InvalidTransition,
    active_offers,
    capture_voice,
    get_rules,
    transition_demand,
    voice_samples,
)
from cci_core.db import get_db
from cci_core.models import DemandState, DemandTopic, Offer, Outcome

router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(require_admin)])


# ------------------------------------------------------ demand-item state machine


class TransitionIn(BaseModel):
    to: str  # new|idea|drafting|published|loop_closed|dismissed
    published_post_id: str | None = None


@router.post("/demand/{topic_id}/transition")
def transition(topic_id: str, body: TransitionIn, db: Session = Depends(get_db)) -> dict:
    topic = db.get(DemandTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="demand topic not found")
    try:
        to_state = DemandState(body.to)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid state '{body.to}'")
    try:
        transition_demand(db, topic, to_state, published_post_id=body.published_post_id)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"id": topic.id, "state": topic.state.value,
            "published_post_id": topic.published_post_id}


@router.get("/creators/{creator_id}/demand/pipeline")
def demand_pipeline(creator_id: str, db: Session = Depends(get_db)) -> dict:
    """Demand items grouped by lifecycle state — the production board."""
    rows = db.scalars(select(DemandTopic).where(DemandTopic.creator_id == creator_id)).all()
    board: dict[str, list] = {s.value: [] for s in DemandState}
    for c in rows:
        board[c.state.value].append({"id": c.id, "label": c.label,
                                     "recommendation": c.recommendation})
    return board


# ----------------------------------------------------------------- voice memory


class VoiceIn(BaseModel):
    kind: str  # reply | hook | caption | dm | draft_edit
    text: str
    prompt_context: str | None = None
    original_draft: str | None = None
    source: str = "approved"


@router.post("/creators/{creator_id}/voice")
def add_voice(creator_id: str, body: VoiceIn, db: Session = Depends(get_db)) -> dict:
    ex = capture_voice(db, creator_id, body.kind, body.text,
                       prompt_context=body.prompt_context,
                       original_draft=body.original_draft, source=body.source)
    return {"id": ex.id}


@router.get("/creators/{creator_id}/voice")
def list_voice(creator_id: str, kind: str | None = None, limit: int = 20,
               db: Session = Depends(get_db)) -> list[dict]:
    samples = voice_samples(db, creator_id, kind, limit)
    return [{"id": s.id, "kind": s.kind, "text": s.text, "source": s.source} for s in samples]


# --------------------------------------------------------------------- offers


class OfferIn(BaseModel):
    name: str
    kind: str  # product | course | coaching | newsletter | launch
    url: str | None = None
    product_id: str | None = None
    topics: list[str] | None = None
    priority: int = 0
    active: bool = True


@router.post("/creators/{creator_id}/offers")
def add_offer(creator_id: str, body: OfferIn, db: Session = Depends(get_db)) -> dict:
    offer = Offer(creator_id=creator_id, **body.model_dump())
    db.add(offer)
    db.flush()
    return {"id": offer.id}


@router.get("/creators/{creator_id}/offers")
def list_offers(creator_id: str, only_active: bool = False,
                db: Session = Depends(get_db)) -> list[dict]:
    offers = active_offers(db, creator_id) if only_active else db.scalars(
        select(Offer).where(Offer.creator_id == creator_id)).all()
    return [{"id": o.id, "name": o.name, "kind": o.kind, "url": o.url,
             "topics": o.topics, "priority": o.priority, "active": o.active} for o in offers]


@router.delete("/offers/{offer_id}")
def delete_offer(offer_id: str, db: Session = Depends(get_db)) -> dict:
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="offer not found")
    db.delete(offer)
    return {"ok": True}


# ----------------------------------------------------------- rules & preferences


class RulesIn(BaseModel):
    tone: str | None = None
    taboo_topics: list[str] | None = None
    escalate_topics: list[str] | None = None
    monetization_priority: str | None = None
    auto_approve_types: list[str] | None = None


@router.get("/creators/{creator_id}/rules")
def read_rules(creator_id: str, db: Session = Depends(get_db)) -> dict:
    r = get_rules(db, creator_id)
    return {"tone": r.tone, "taboo_topics": r.taboo_topics, "escalate_topics": r.escalate_topics,
            "monetization_priority": r.monetization_priority,
            "auto_approve_types": r.auto_approve_types}


@router.put("/creators/{creator_id}/rules")
def update_rules(creator_id: str, body: RulesIn, db: Session = Depends(get_db)) -> dict:
    from cci_core.agent_foundations import utcnow

    r = get_rules(db, creator_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(r, field, value)
    r.updated_at = utcnow()
    return {"ok": True}


# --------------------------------------------------------------------- outcomes


@router.get("/creators/{creator_id}/outcomes")
def list_outcomes(creator_id: str, stage: str | None = None, limit: int = 50,
                  db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Outcome).where(Outcome.creator_id == creator_id)
    if stage:
        stmt = stmt.where(Outcome.stage == stage)
    rows = db.scalars(stmt.order_by(Outcome.created_at.desc()).limit(limit)).all()
    return [{"id": o.id, "source": o.source, "question": o.question_text,
             "served_state": o.served_state, "stage": o.stage,
             "creator_action": o.creator_action, "result": o.result} for o in rows]
