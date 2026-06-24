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


@router.get("/creators/{creator_id}/north-star")
def north_star(creator_id: str, weeks: int = 8, db: Session = Depends(get_db)) -> dict:
    """Closed demand loops per active creator per week — the company metric."""
    from cci_agent.demand import closed_loops

    return closed_loops(db, creator_id, weeks=weeks)


@router.get("/demand/{topic_id}/opportunity")
def opportunity(topic_id: str, db: Session = Depends(get_db)) -> dict:
    """Re-score a demand item, exposing every Opportunity Score component."""
    from cci_agent.demand import score_topic

    topic = db.get(DemandTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="demand topic not found")
    return score_topic(db, topic)


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


@router.get("/creators/{creator_id}/permissions")
def read_permissions(creator_id: str, db: Session = Depends(get_db)) -> dict:
    """The trust-calibrated permission ladder per action, + pause state."""
    from cci_agent.permissions import permission_summary

    return permission_summary(db, creator_id)


class PermissionIn(BaseModel):
    action: str
    level: str  # recommend | draft | batch | auto


@router.put("/creators/{creator_id}/permissions")
def set_permission_endpoint(creator_id: str, body: PermissionIn,
                            db: Session = Depends(get_db)) -> dict:
    from cci_agent.permissions import set_permission

    try:
        effective = set_permission(db, creator_id, body.action, body.level)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"action": body.action, "level": effective}  # may be clamped to the ceiling


@router.post("/creators/{creator_id}/automation/pause")
def pause_automation_endpoint(creator_id: str, paused: bool = True,
                              db: Session = Depends(get_db)) -> dict:
    from cci_agent.permissions import pause_automation

    pause_automation(db, creator_id, paused=paused)
    return {"automation_paused": paused}


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


# ============================================================ v1.5 assist features


# ---------------------------------------------------- content production (drafting)


@router.post("/demand/{topic_id}/draft")
def make_draft(topic_id: str, db: Session = Depends(get_db)) -> dict:
    """Generate a grounded content brief + reel script/hooks from a demand cluster."""
    from cci_agent.drafting import generate_draft
    from cci_core import events
    from cci_core.agent_foundations import DemandState, transition_demand
    from cci_core.billing import PlanError, assert_feature, check_quota

    topic = db.get(DemandTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="demand topic not found")
    # plan gating: drafting is a Pro feature, metered against the monthly quota
    try:
        assert_feature(db, topic.creator_id, "draft_generator")
        check_quota(db, topic.creator_id, "drafts")
    except PlanError as exc:
        raise HTTPException(status_code=402, detail={"error": str(exc), "code": exc.code})
    draft = generate_draft(db, topic.creator_id, topic, persist=True)
    events.track(db, "drafts", topic.creator_id, draft_id=draft.id)
    # advance the lifecycle if the creator is acting on it
    if topic.state in (DemandState.new, DemandState.idea):
        try:
            transition_demand(db, topic,
                              DemandState.drafting if topic.state == DemandState.idea
                              else DemandState.idea)
        except Exception:  # noqa: BLE001
            pass
    return {"draft_id": draft.id, "title": draft.title, "hooks": draft.hooks,
            "script": draft.script, "cta": draft.cta, "brief": draft.brief}


@router.get("/creators/{creator_id}/drafts")
def list_drafts(creator_id: str, db: Session = Depends(get_db)) -> list[dict]:
    from cci_core.models import ContentDraft

    rows = db.scalars(
        select(ContentDraft).where(ContentDraft.creator_id == creator_id)
        .order_by(ContentDraft.created_at.desc())
    ).all()
    return [{"id": d.id, "title": d.title, "hooks": d.hooks, "script": d.script,
             "cta": d.cta, "status": d.status, "demand_topic_id": d.demand_topic_id}
            for d in rows]


class DraftDecision(BaseModel):
    approve: bool
    edited_script: str | None = None


@router.post("/drafts/{draft_id}/decide")
def decide_draft(draft_id: str, body: DraftDecision, db: Session = Depends(get_db)) -> dict:
    """Approve (capturing voice) or leave a draft; never auto-publishes."""
    from cci_core.agent_foundations import capture_voice
    from cci_core.models import ContentDraft

    draft = db.get(ContentDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    if body.approve:
        if body.edited_script and body.edited_script != draft.script:
            capture_voice(db, draft.creator_id, "caption", body.edited_script,
                          original_draft=draft.script, source="edit")
            draft.script = body.edited_script
        elif draft.hooks:
            capture_voice(db, draft.creator_id, "hook", draft.hooks[0], source="approved")
        draft.status = "approved"
    return {"id": draft.id, "status": draft.status}


@router.get("/creators/{creator_id}/recall")
def recall(creator_id: str, q: str, db: Session = Depends(get_db)) -> list[dict]:
    """Creator recall search: 'where did I say that?'"""
    from cci_agent.drafting import creator_recall

    return creator_recall(db, creator_id, q)


# ---------------------------------------------------------- versioned claim layer


@router.get("/creators/{creator_id}/claims")
def list_claims(creator_id: str, validity: str | None = None,
                db: Session = Depends(get_db)) -> list[dict]:
    from cci_core.models import Claim

    stmt = select(Claim).where(Claim.creator_id == creator_id)
    if validity:
        stmt = stmt.where(Claim.validity == validity)
    rows = db.scalars(stmt.order_by(Claim.created_at.desc()).limit(200)).all()
    return [{"id": c.id, "text": c.text, "topic": c.topic, "post_id": c.post_id,
             "validity": c.validity.value, "approved": c.approved,
             "superseded_by": c.superseded_by} for c in rows]


@router.post("/claims/{claim_id}/approve")
def approve_claim_endpoint(claim_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.claims import approve_claim

    claim = approve_claim(db, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return {"id": claim.id, "approved": claim.approved}


@router.post("/creators/{creator_id}/claims/detect-contradictions")
def detect_contradictions_endpoint(creator_id: str, db: Session = Depends(get_db)) -> dict:
    """Mark older claims superseded by newer contradicting ones (freshness handling)."""
    from cci_agent.claims import detect_contradictions

    return {"superseded": detect_contradictions(db, creator_id)}


# ------------------------------------------------------------- briefing + gap map


@router.get("/creators/{creator_id}/briefing")
def briefing(creator_id: str, with_draft: bool = True, db: Session = Depends(get_db)) -> dict:
    from cci_agent.briefing import build_briefing

    result = build_briefing(db, creator_id, with_draft=with_draft)
    if result is None:
        raise HTTPException(status_code=404, detail="no demand signal yet this week")
    return result


@router.get("/creators/{creator_id}/gap-map")
def gap_map(creator_id: str, week: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    from cci_agent.briefing import content_gap_map

    return content_gap_map(db, creator_id, week)


# --------------------------------------------------------------- inbox + playbooks


@router.get("/creators/{creator_id}/inbox")
def inbox(creator_id: str, limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    from cci_agent.inbox import labelled_inbox

    return labelled_inbox(db, creator_id, limit)


class PlaybookIn(BaseModel):
    name: str
    trigger_keywords: list[str] | None = None
    intent: str | None = None
    public_reply_template: str | None = None
    dm_template: str | None = None


@router.post("/creators/{creator_id}/playbooks")
def add_playbook(creator_id: str, body: PlaybookIn, db: Session = Depends(get_db)) -> dict:
    from cci_core.models import Playbook

    pb = Playbook(creator_id=creator_id, **body.model_dump())
    db.add(pb)
    db.flush()
    return {"id": pb.id}


@router.get("/creators/{creator_id}/playbooks")
def list_playbooks(creator_id: str, db: Session = Depends(get_db)) -> list[dict]:
    from cci_core.models import Playbook

    rows = db.scalars(select(Playbook).where(Playbook.creator_id == creator_id)).all()
    return [{"id": p.id, "name": p.name, "trigger_keywords": p.trigger_keywords,
             "intent": p.intent, "active": p.active} for p in rows]


# ============================================================ v2 agent features


# ---------------------------------------------------------------- engagement


class BulkApproveIn(BaseModel):
    job_ids: list[str]


@router.post("/creators/{creator_id}/dm/bulk-approve")
def dm_bulk_approve(creator_id: str, body: BulkApproveIn, db: Session = Depends(get_db)) -> dict:
    from cci_agent.engagement import bulk_approve

    return {"approved": bulk_approve(db, creator_id, body.job_ids)}


@router.post("/demand/{topic_id}/close-loop")
def close_loop_endpoint(topic_id: str, db: Session = Depends(get_db)) -> dict:
    """Loop-Closer: notify the original askers (approval-mode DMs, 7-day window)."""
    from cci_agent.engagement import close_loop
    from cci_core.models import Creator

    topic = db.get(DemandTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="demand topic not found")
    creator = db.get(Creator, topic.creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="creator not found")
    created = close_loop(db, topic, creator.handle)
    return {"notified": len(created), "state": topic.state.value}


class DeferIn(BaseModel):
    question: str
    weeks: int = 6
    comment_id: str | None = None
    demand_topic_id: str | None = None


@router.post("/creators/{creator_id}/defer")
def defer(creator_id: str, body: DeferIn, db: Session = Depends(get_db)) -> dict:
    from cci_agent.engagement import defer_question

    item = defer_question(db, creator_id, body.question, weeks=body.weeks,
                          comment_id=body.comment_id, demand_topic_id=body.demand_topic_id)
    return {"id": item.id, "remind_at": item.remind_at.isoformat()}


@router.get("/creators/{creator_id}/deferrals/due")
def deferrals_due(creator_id: str, db: Session = Depends(get_db)) -> list[dict]:
    from cci_agent.engagement import due_deferrals

    return [{"id": d.id, "question": d.question, "remind_at": d.remind_at.isoformat()}
            for d in due_deferrals(db, creator_id)]


# ---------------------------------------------------------------- intelligence


@router.get("/creators/{creator_id}/personas")
def personas(creator_id: str, db: Session = Depends(get_db)) -> list[dict]:
    from cci_agent.intelligence import segment_personas

    return segment_personas(db, creator_id)


@router.get("/creators/{creator_id}/sentiment")
def sentiment(creator_id: str, days: int = 30, db: Session = Depends(get_db)) -> dict:
    from cci_agent.intelligence import sentiment_summary

    return sentiment_summary(db, creator_id, days)


@router.get("/creators/{creator_id}/trends")
def trends(creator_id: str, db: Session = Depends(get_db)) -> list[dict]:
    from cci_agent.intelligence import detect_trends

    return detect_trends(db, creator_id)


class StrategyIn(BaseModel):
    question: str


@router.post("/creators/{creator_id}/strategy")
def strategy(creator_id: str, body: StrategyIn, db: Session = Depends(get_db)) -> dict:
    from cci_agent.intelligence import strategy_advisor

    return strategy_advisor(db, creator_id, body.question)


class ExternalSignalIn(BaseModel):
    platform: str  # newsletter | podcast | youtube | dm_forward
    text: str
    is_question: bool = True


@router.post("/creators/{creator_id}/external-signal")
def add_external_signal(creator_id: str, body: ExternalSignalIn,
                        db: Session = Depends(get_db)) -> dict:
    """Cross-platform demand intake (newsletter BCC, podcast comments, forwarded DMs)."""
    from cci_core.models import ExternalSignal

    sig = ExternalSignal(creator_id=creator_id, **body.model_dump())
    db.add(sig)
    db.flush()
    return {"id": sig.id}


# ---------------------------------------------------------------- repurposing


@router.post("/posts/{post_id}/repurpose")
def repurpose_post(post_id: str, target_format: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.repurposing import repurpose

    try:
        return repurpose(db, post_id, target_format)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/demand/{topic_id}/series")
def series(topic_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.repurposing import build_series

    topic = db.get(DemandTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="demand topic not found")
    return build_series(db, topic.creator_id, topic)


# ---------------------------------------------------------------- revenue


@router.get("/creators/{creator_id}/sponsor-report")
def sponsor_report_endpoint(creator_id: str, topic: str | None = None,
                            db: Session = Depends(get_db)) -> dict:
    from cci_agent.revenue import sponsor_report
    from cci_core.billing import PlanError, assert_feature

    try:
        assert_feature(db, creator_id, "sponsor_reports")  # Pro feature
    except PlanError as exc:
        raise HTTPException(status_code=402, detail={"error": str(exc), "code": exc.code})
    return sponsor_report(db, creator_id, topic)


@router.get("/creators/{creator_id}/affiliate-optimisation")
def affiliate_opt(creator_id: str, db: Session = Depends(get_db)) -> list[dict]:
    from cci_agent.revenue import affiliate_optimisation

    return affiliate_optimisation(db, creator_id)


# ---------------------------------------------------------------- brand


@router.get("/creators/{creator_id}/crisis-check")
def crisis_check(creator_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.brand import detect_crisis

    return detect_crisis(db, creator_id)


class VoiceScoreIn(BaseModel):
    text: str


@router.post("/creators/{creator_id}/voice-score")
def voice_score(creator_id: str, body: VoiceScoreIn, db: Session = Depends(get_db)) -> dict:
    from cci_agent.brand import voice_consistency_score

    return voice_consistency_score(db, creator_id, body.text)


# ============================================================ v3 scale features


@router.get("/drafts/{draft_id}/predict")
def predict(draft_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.scale import predict_performance
    from cci_core.models import ContentDraft

    draft = db.get(ContentDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    return predict_performance(db, draft.creator_id, draft)


@router.get("/creators/{creator_id}/calendar")
def calendar(creator_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.scale import content_calendar

    return content_calendar(db, creator_id)


@router.get("/creators/{creator_id}/pricing-insights")
def pricing(creator_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.scale import pricing_insights

    return pricing_insights(db, creator_id)


@router.get("/creators/{creator_id}/revenue-forecast")
def forecast(creator_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.scale import revenue_forecast

    return revenue_forecast(db, creator_id)


@router.get("/creators/{creator_id}/education-plan")
def education(creator_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.scale import education_plan

    return education_plan(db, creator_id)


# ---------------------------------------------------------------- CRM


@router.get("/creators/{creator_id}/customers")
def customers(creator_id: str, db: Session = Depends(get_db)) -> list[dict]:
    from cci_agent.crm import customer_profiles

    return customer_profiles(db, creator_id)


@router.get("/creators/{creator_id}/lifecycle")
def lifecycle(creator_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.crm import lifecycle_segments

    return lifecycle_segments(db, creator_id)


# ---------------------------------------------------------------- team & roles


class MemberIn(BaseModel):
    email: str
    role: str  # owner | creator | analytics | contractor


@router.post("/creators/{creator_id}/team")
def add_team_member(creator_id: str, body: MemberIn, db: Session = Depends(get_db)) -> dict:
    from cci_agent.team import add_member, audit
    from cci_core.models import TeamRole

    try:
        role = TeamRole(body.role)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid role '{body.role}'")
    member = add_member(db, creator_id, body.email, role)
    audit(db, creator_id, "admin", "add_team_member", {"email": body.email, "role": body.role})
    return {"id": member.id, "role": member.role.value}


@router.get("/creators/{creator_id}/team")
def list_team(creator_id: str, db: Session = Depends(get_db)) -> list[dict]:
    from cci_core.models import TeamMember

    rows = db.scalars(select(TeamMember).where(TeamMember.creator_id == creator_id)).all()
    return [{"id": m.id, "email": m.email, "role": m.role.value} for m in rows]


class ApiKeyIn(BaseModel):
    name: str
    scopes: list[str] | None = None


@router.post("/creators/{creator_id}/api-keys")
def create_api_key(creator_id: str, body: ApiKeyIn, db: Session = Depends(get_db)) -> dict:
    from cci_agent.team import mint_api_key

    record, full = mint_api_key(db, creator_id, body.name, body.scopes)
    return {"id": record.id, "key": full, "note": "store this now — it is shown only once"}


@router.delete("/api-keys/{key_id}")
def revoke_key(key_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.team import revoke_api_key

    if not revoke_api_key(db, key_id):
        raise HTTPException(status_code=404, detail="key not found")
    return {"revoked": True}


# ---------------------------------------------------------------- growth & ecosystem


@router.get("/creators/{creator_id}/benchmark")
def benchmark(creator_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.growth import peer_benchmark

    return peer_benchmark(db, creator_id)


@router.get("/creators/{creator_id}/competitor-radar")
def competitor(creator_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_agent.growth import competitor_radar

    return competitor_radar(db, creator_id)


class PlagiarismIn(BaseModel):
    text: str


@router.post("/creators/{creator_id}/plagiarism-scan")
def plagiarism(creator_id: str, body: PlagiarismIn, db: Session = Depends(get_db)) -> dict:
    from cci_agent.growth import plagiarism_scan

    return plagiarism_scan(db, creator_id, body.text)


@router.post("/demand/{topic_id}/export-task")
def export_task_endpoint(topic_id: str, provider: str = "fake",
                         db: Session = Depends(get_db)) -> dict:
    from cci_agent.growth import export_task

    topic = db.get(DemandTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="demand topic not found")
    return export_task(db, topic.creator_id, topic, provider)
