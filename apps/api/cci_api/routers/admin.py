"""Admin/operator API: creators, DM approval queue, Demand Radar review,
products, metrics. v1 = single operator with a bearer token (manual onboarding)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cci_api.deps import require_admin
from cci_core import events
from cci_core.db import get_db
from cci_core.models import (
    Comment, Creator, CreatorStatus, DemandTopic, DmJob, DmStatus, Event,
    OAuthToken, PlatformAccount, Post, PostStatus, Product, Query,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---------------------------------------------------------------------- creators


class CreatorIn(BaseModel):
    handle: str
    display_name: str
    ig_user_id: str | None = None
    yt_channel_id: str | None = None
    niche: str | None = None


@router.post("/creators")
def create_creator(body: CreatorIn, db: Session = Depends(get_db)) -> dict:
    creator = Creator(**body.model_dump(), status=CreatorStatus.active)
    db.add(creator)
    db.flush()
    return {"id": creator.id, "handle": creator.handle}


@router.get("/creators")
def list_creators(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Creator)).all()
    return [{"id": c.id, "handle": c.handle, "display_name": c.display_name,
             "status": c.status.value} for c in rows]


@router.get("/versions")
def ai_versions() -> dict:
    """The AI version registry — which model/version powers each component (for
    reproducibility and planned re-embed/re-enrich migrations)."""
    from cci_providers import provider_versions

    return provider_versions()


@router.get("/platforms")
def platforms() -> list[dict]:
    """Every platform Sift can connect, with the capabilities its connector advertises."""
    from cci_core.connectors import capabilities_for, supported_platforms

    return [{"platform": p, "capabilities": sorted(capabilities_for(p))}
            for p in supported_platforms()]


@router.get("/creators/{creator_id}/connectors")
def creator_connectors(creator_id: str, db: Session = Depends(get_db)) -> list[dict]:
    """The creator's connected platforms and what each can actually do — the UI/agent
    use this to show only the actions an account supports."""
    from cci_core.connectors import capabilities_for

    tokens = db.scalars(select(OAuthToken).where(
        OAuthToken.creator_id == creator_id)).all()
    return [{"platform": t.platform, "connected": True,
             "capabilities": sorted(capabilities_for(t.platform))} for t in tokens]


class TokenIn(BaseModel):
    platform: str
    access_token: str
    scopes: str | None = None


@router.put("/creators/{creator_id}/token")
def set_token(creator_id: str, body: TokenIn, db: Session = Depends(get_db)) -> dict:
    existing = db.scalar(select(OAuthToken).where(
        OAuthToken.creator_id == creator_id, OAuthToken.platform == body.platform))
    if existing:
        existing.access_token = body.access_token
        existing.scopes = body.scopes
    else:
        db.add(OAuthToken(creator_id=creator_id, platform=body.platform,
                          access_token=body.access_token, scopes=body.scopes))
    return {"ok": True}


@router.post("/creators/{creator_id}/backfill")
def trigger_backfill(creator_id: str) -> dict:
    from cci_workers.queue import INGEST, get_queue

    job = get_queue(INGEST).enqueue("cci_workers.ingest_instagram.backfill_creator",
                                    creator_id, job_timeout=3600 * 6)
    return {"job_id": job.id}


@router.post("/creators/{creator_id}/sync-native")
def trigger_native_sync(creator_id: str, platform: str = "youtube",
                        db: Session = Depends(get_db)) -> dict:
    """Backfill a connected native platform (e.g. YouTube) through its connector.
    Validates the connector + authorization synchronously, then enqueues the sync."""
    from cci_core.connectors import capabilities_for
    from cci_core.connectors.base import CONTENT_READ
    from cci_workers.queue import INGEST, get_queue

    if CONTENT_READ not in capabilities_for(platform):
        raise HTTPException(status_code=400,
                            detail=f"'{platform}' has no native content connector")
    token = db.scalar(select(OAuthToken).where(
        OAuthToken.creator_id == creator_id, OAuthToken.platform == platform))
    if token is None:
        raise HTTPException(
            status_code=400,
            detail=f"no {platform} authorization — connect the account first")
    account = db.scalar(select(PlatformAccount).where(
        PlatformAccount.creator_id == creator_id, PlatformAccount.platform == platform))
    job = get_queue(INGEST).enqueue("cci_workers.sync_native.sync_native",
                                    creator_id, platform, job_timeout=3600 * 3)
    return {"job_id": job.id, "platform": platform,
            "channel": account.external_account_id if account else None}


@router.post("/creators/{creator_id}/process")
def trigger_processing(creator_id: str) -> dict:
    from cci_workers.queue import INGEST, get_queue

    job = get_queue(INGEST).enqueue("cci_workers.enrich.process_all_pending",
                                    creator_id, job_timeout=3600 * 12)
    return {"job_id": job.id}


@router.post("/creators/{creator_id}/reindex")
def trigger_reindex(creator_id: str, db: Session = Depends(get_db)) -> dict:
    """Planned re-embed (e.g. after an embedding model swap)."""
    from cci_retrieval.indexer import reindex_creator

    return {"chunks": reindex_creator(db, creator_id)}


@router.delete("/creators/{creator_id}/posts/{post_id}")
def delete_post(creator_id: str, post_id: str, db: Session = Depends(get_db)) -> dict:
    """Manual deletion path (GDPR/cleanup): tombstone + purge from index."""
    from cci_retrieval.indexer import purge_post

    post = db.get(Post, post_id)
    if post is None or post.creator_id != creator_id:
        raise HTTPException(status_code=404, detail="post not found")
    purge_post(db, post)
    return {"ok": True}


# ----------------------------------------------------------- GDPR / data rights


@router.get("/creators/{creator_id}/export")
def export_data(creator_id: str, db: Session = Depends(get_db)) -> dict:
    """Portable export of all of a creator's data (GDPR Art. 20)."""
    from cci_core.gdpr import export_creator_data

    data = export_creator_data(db, creator_id)
    if not data:
        raise HTTPException(status_code=404, detail="creator not found")
    return data


@router.delete("/creators/{creator_id}")
def erase_creator(creator_id: str, db: Session = Depends(get_db)) -> dict:
    """Full erasure of a creator and all dependent data (GDPR Art. 17)."""
    from cci_core.gdpr import delete_creator

    if not delete_creator(db, creator_id):
        raise HTTPException(status_code=404, detail="creator not found")
    return {"erased": True}


class AudienceErasureIn(BaseModel):
    pseudonym: str | None = None
    email: str | None = None


@router.post("/creators/{creator_id}/erase-audience")
def erase_audience(creator_id: str, body: AudienceErasureIn,
                   db: Session = Depends(get_db)) -> dict:
    """Erase one audience member's data by pseudonym, and/or a captured lead by email."""
    from cci_core.gdpr import erase_audience_member, forget_waitlist_email

    result: dict = {}
    if body.pseudonym:
        result.update(erase_audience_member(db, creator_id, body.pseudonym))
    if body.email:
        result["waitlist_removed"] = forget_waitlist_email(db, creator_id, body.email)
    if not result:
        raise HTTPException(status_code=422, detail="provide a pseudonym and/or email")
    return result


# ------------------------------------------------------------ DM approval queue


@router.get("/creators/{creator_id}/dm-queue")
def dm_queue(creator_id: str, db: Session = Depends(get_db)) -> list[dict]:
    jobs = db.scalars(
        select(DmJob).where(DmJob.creator_id == creator_id,
                            DmJob.status == DmStatus.pending_approval)
        .order_by(DmJob.created_at)
    ).all()
    out = []
    for job in jobs:
        comment = db.get(Comment, job.comment_id)
        out.append({
            "job_id": job.id,
            "comment": comment.text if comment else None,
            "public_reply": job.public_reply,
            "dm_text": job.dm_text,
            "deep_link": job.deep_link,
            "confidence": job.confidence,
            "created_at": job.created_at.isoformat(),
        })
    return out


class DmDecision(BaseModel):
    approve: bool
    edited_dm_text: str | None = None
    edited_public_reply: str | None = None


@router.post("/dm-jobs/{job_id}/decide")
def decide_dm(job_id: str, body: DmDecision, db: Session = Depends(get_db)) -> dict:
    job = db.get(DmJob, job_id)
    if job is None or job.status != DmStatus.pending_approval:
        raise HTTPException(status_code=404, detail="job not found or already decided")
    if body.approve:
        # voice memory: an edited approval teaches the creator's voice (foundations)
        from cci_core.agent_foundations import capture_voice

        if body.edited_dm_text and body.edited_dm_text != job.dm_text:
            capture_voice(db, job.creator_id, "dm", body.edited_dm_text,
                          original_draft=job.dm_text, source="edit")
            job.dm_text = body.edited_dm_text
        elif job.dm_text:
            capture_voice(db, job.creator_id, "dm", job.dm_text, source="approved")
        if body.edited_public_reply:
            job.public_reply = body.edited_public_reply
        job.status = DmStatus.approved
    else:
        job.status = DmStatus.rejected
    return {"status": job.status.value}


# ------------------------------------------------------------------ Demand Radar


@router.get("/creators/{creator_id}/radar")
def radar_cards(creator_id: str, week: str | None = None,
                db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(DemandTopic).where(DemandTopic.creator_id == creator_id)
    if week:
        stmt = stmt.where(DemandTopic.week == week)
    # rank by the explainable Opportunity Score (falls back to raw demand)
    cards = db.scalars(stmt.order_by(
        DemandTopic.opportunity_score.desc().nullslast(),
        (DemandTopic.search_count + DemandTopic.comment_count).desc())).all()
    return [{
        "id": c.id, "label": c.label, "week": c.week,
        "search_count": c.search_count, "comment_count": c.comment_count,
        "wow_change": c.wow_change, "coverage": c.coverage,
        "audience_language": c.audience_language, "recommendation": c.recommendation,
        "linked_products": c.linked_products, "confidence": c.confidence,
        "creator_marked": c.creator_marked, "state": c.state.value,
        "opportunity_score": c.opportunity_score,
        "opportunity_components": c.opportunity_components,
        "integrity": {
            "unique_askers": c.unique_askers, "organic_count": c.organic_count,
            "prompted_count": c.prompted_count, "persistence_weeks": c.persistence_weeks,
            "dominant_sentiment": c.dominant_sentiment, "intent_class": c.intent_class,
        },
    } for c in cards]


class RadarMark(BaseModel):
    marked: str  # useful | not | made


@router.post("/radar/{card_id}/mark")
def mark_radar_card(card_id: str, body: RadarMark, db: Session = Depends(get_db)) -> dict:
    """The decide-it metric: does the creator act on Radar without persuasion?"""
    card = db.get(DemandTopic, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="card not found")
    if body.marked not in ("useful", "not", "made"):
        raise HTTPException(status_code=422, detail="marked must be useful|not|made")
    card.creator_marked = body.marked
    events.track(db, events.RADAR_MARKED, card.creator_id, card_id=card_id, marked=body.marked)
    return {"ok": True}


@router.post("/creators/{creator_id}/radar/build")
def trigger_radar(creator_id: str, backlog: bool = False) -> dict:
    from cci_workers.queue import PERIODIC, get_queue

    job = get_queue(PERIODIC).enqueue("cci_workers.radar.build_radar", creator_id,
                                      backlog=backlog)
    return {"job_id": job.id}


# --------------------------------------------------------------------- products


class ProductIn(BaseModel):
    name: str
    affiliate_url: str | None = None
    approved: bool = False


@router.post("/creators/{creator_id}/products")
def add_product(creator_id: str, body: ProductIn, db: Session = Depends(get_db)) -> dict:
    product = Product(creator_id=creator_id, **body.model_dump())
    db.add(product)
    db.flush()
    return {"id": product.id}


@router.get("/creators/{creator_id}/products")
def list_products(creator_id: str, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Product).where(Product.creator_id == creator_id)).all()
    return [{"id": p.id, "name": p.name, "affiliate_url": p.affiliate_url,
             "approved": p.approved} for p in rows]


# ---------------------------------------------------------------------- metrics


@router.get("/creators/{creator_id}/metrics")
def metrics(creator_id: str, days: int = 7, db: Session = Depends(get_db)) -> dict:
    """The plan-§8 dashboard in one JSON blob."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    def count(kind: str) -> int:
        return db.scalar(
            select(func.count(Event.id)).where(
                Event.creator_id == creator_id, Event.kind == kind, Event.ts >= since)
        ) or 0

    n_posts = db.scalar(select(func.count(Post.id)).where(
        Post.creator_id == creator_id, Post.status == PostStatus.active)) or 0
    n_questions = db.scalar(select(func.count(Comment.id)).where(
        Comment.creator_id == creator_id, Comment.is_question.is_(True))) or 0
    n_queries = db.scalar(select(func.count(Query.id)).where(
        Query.creator_id == creator_id, Query.created_at >= since)) or 0
    searches = count(events.SEARCH)
    return {
        "window_days": days,
        "corpus": {"active_posts": n_posts, "question_comments_total": n_questions},
        "audience": {
            "searches": searches,
            "result_clicks": count(events.RESULT_CLICK),
            "click_rate": round(count(events.RESULT_CLICK) / searches, 3) if searches else None,
            "deeplink_opens": count(events.DEEPLINK_OPEN),
            "no_answer_rate": round(count(events.NO_ANSWER) / searches, 3) if searches else None,
            "logged_queries": n_queries,
        },
        "dm": {"queued": count(events.DM_QUEUED), "sent": count(events.DM_SENT),
               "fallbacks": count(events.DM_FALLBACK)},
        "monetization": {"affiliate_clicks": count(events.AFFILIATE_CLICK)},
    }
