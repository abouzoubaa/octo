"""Public audience API — no login wall (plan §3: built for the in-app browser).

Every search and click is logged as a demand signal: the query IS the asset.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_api.deps import get_creator
from cci_api.observability import rate_limit
from cci_core import events
from cci_core.db import get_db
from cci_core.models import (
    Answer, Creator, Post, Product, ProductLink, Query, QuerySource,
)
from cci_retrieval.answer import generate_answer, persist_answer
from cci_retrieval.search import search

router = APIRouter(tags=["public"])


class EvidenceOut(BaseModel):
    source: str
    text: str
    start_ts: float | None


class ResultOut(BaseModel):
    post_id: str
    permalink: str | None
    caption: str | None
    post_type: str
    posted_at: str | None
    score: float
    evidence: list[EvidenceOut]
    products: list[dict] = []
    language: str | None = None


class CitationOut(BaseModel):
    n: int
    post_id: str
    permalink: str | None
    quote: str


class AnswerOut(BaseModel):
    state: str
    text: str | None
    citations: list[CitationOut] = []
    confidence: float
    answer_id: str | None = None
    freshness: list[dict] = []  # 'the creator later updated this' notes (claim layer)
    # bounded clarifying question (agent §05): one either/or to disambiguate a vague
    # search when there's no strong answer — not open chat. {question, options: [a, b]}
    clarify: dict | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[ResultOut]
    answer: AnswerOut | None = None
    deep_link: str


@router.get("/api/{handle}/search", response_model=SearchResponse,
            dependencies=[Depends(rate_limit)])
def search_endpoint(
    q: str = QueryParam(..., min_length=1, max_length=500),
    with_answer: bool = QueryParam(default=True),
    creator: Creator = Depends(get_creator),
    db: Session = Depends(get_db),
) -> SearchResponse:
    from cci_core.deep_links import answer_link, search_link

    answer_out: AnswerOut | None = None
    answer_id: str | None = None

    if with_answer:
        # the answer card is a free, anonymous LLM call — bound it by a per-creator
        # monthly abuse ceiling (distinct from the plan cost cap, so free creators keep
        # their answer card). Over the ceiling, degrade to plain search (no LLM).
        from cci_core.config import get_settings
        from cci_core.cost import monthly_cost_cents

        cap = get_settings().anon_answer_monthly_cap_cents
        if cap and monthly_cost_cents(db, creator.id, op="answer") >= cap:
            with_answer = False

    if with_answer:
        card = generate_answer(db, creator.id, q)
        results = card.results
        if card.state == "answered":
            persisted = persist_answer(db, creator.id, card)
            answer_id = persisted.id
        clarify = None
        if card.state == "no_strong_answer":
            from cci_agent.inbox import bounded_clarify

            clarify = bounded_clarify(q)
        answer_out = AnswerOut(
            state=card.state, text=card.text,
            citations=[CitationOut(**c) for c in card.citations],
            confidence=round(card.confidence, 3), answer_id=answer_id,
            freshness=_freshness_for(db, card),
            clarify=clarify,
        )
    else:
        results = search(db, creator.id, q)

    # log the demand signal
    query_row = Query(
        creator_id=creator.id, source=QuerySource.search, text=q,
        result_post_ids=[r.post_id for r in results],
        answer_id=answer_id,
        confidence=answer_out.confidence if answer_out else None,
    )
    db.add(query_row)
    db.flush()
    events.track(db, events.SEARCH, creator.id, q=q, n_results=len(results))
    if answer_out and answer_out.state == "no_strong_answer":
        events.track(db, events.NO_ANSWER, creator.id, q=q)

    # outcome log: open the outcome edge for this served search (agent foundations)
    if answer_out is not None:
        from cci_core.agent_foundations import record_outcome

        record_outcome(
            db, creator.id, source="search", question_text=q, query_id=query_row.id,
            answer_id=answer_id, served_state=answer_out.state, confidence=answer_out.confidence,
        )

    deep_link = answer_link(creator.handle, q, answer_id) if answer_id else search_link(creator.handle, q)
    return SearchResponse(
        query=q,
        results=[_result_out(db, r) for r in results],
        answer=answer_out,
        deep_link=deep_link,
    )


def _freshness_for(db: Session, card) -> list[dict]:
    """Flag cited sources the creator later updated (versioned claim layer)."""
    if card.state != "answered":
        return []
    from cci_agent.claims import claim_freshness

    return claim_freshness(db, [c["post_id"] for c in card.citations])


def _result_out(db: Session, r) -> ResultOut:
    product_rows = db.execute(
        select(Product).join(ProductLink, ProductLink.product_id == Product.id)
        .where(ProductLink.post_id == r.post_id, Product.approved.is_(True))
    ).scalars().all()
    return ResultOut(
        post_id=r.post_id, permalink=r.permalink, caption=r.caption,
        post_type=r.post_type, posted_at=r.posted_at, score=round(r.score, 5),
        evidence=[EvidenceOut(source=h.source, text=h.text[:300], start_ts=h.start_ts)
                  for h in r.evidence],
        products=[{"id": p.id, "name": p.name, "is_affiliate": bool(p.affiliate_url),
                   "disclosure": ("Affiliate link — the creator may earn a commission."
                                  if p.affiliate_url else None)}
                  for p in product_rows],
        language=getattr(r, "language", None),
    )


@router.get("/api/{handle}/answer/{answer_id}", response_model=AnswerOut)
def get_answer(answer_id: str, creator: Creator = Depends(get_creator),
               db: Session = Depends(get_db)) -> AnswerOut:
    """Deep-link resolution: the DM/share URL opens with the answer already loaded."""
    answer = db.get(Answer, answer_id)
    if answer is None or answer.creator_id != creator.id:
        raise HTTPException(status_code=404, detail="answer not found")
    events.track(db, events.DEEPLINK_OPEN, creator.id, answer_id=answer_id)
    return AnswerOut(
        state=answer.state.value, text=answer.text,
        citations=[CitationOut(**c) for c in (answer.citations or [])],
        confidence=answer.confidence or 0.0, answer_id=answer.id,
    )


@router.post("/api/{handle}/events/click")
def track_click(post_id: str, creator: Creator = Depends(get_creator),
                db: Session = Depends(get_db)) -> dict:
    events.track(db, events.RESULT_CLICK, creator.id, post_id=post_id)
    return {"ok": True}


class WaitlistIn(BaseModel):
    email: EmailStr
    topic: str = Field(min_length=1, max_length=500)


@router.post("/api/{handle}/waitlist", dependencies=[Depends(rate_limit)])
def join_waitlist(body: WaitlistIn, creator: Creator = Depends(get_creator),
                  db: Session = Depends(get_db)) -> dict:
    """No-answer waitlist / demand cohort: 'want a heads-up when @creator covers
    this?' — captures a lead, feeds the gap map, and returns the cohort size so the
    fan sees 'N people want this' (a non-payment demand contract)."""
    from cci_agent.inbox import add_to_waitlist

    topic = body.topic.strip()
    add_to_waitlist(db, creator.id, body.email.strip(), topic)
    events.track(db, "waitlist_join", creator.id, topic=topic)
    # cohort size: how many distinct people are waiting on a similar topic
    from cci_core.models import WaitlistEntry

    words = {w for w in topic.lower().split() if len(w) > 3}
    cohort = {e for e, t in db.execute(select(WaitlistEntry.email, WaitlistEntry.topic).where(
        WaitlistEntry.creator_id == creator.id, WaitlistEntry.notified.is_(False)))
        if words & {w for w in (t or "").lower().split() if len(w) > 3}}
    return {"ok": True, "cohort_size": max(len(cohort), 1)}


@router.get("/api/{handle}/cohorts")
def open_cohorts(creator: Creator = Depends(get_creator),
                 db: Session = Depends(get_db)) -> list[dict]:
    """Open demand cohorts: topics fans are waiting on, with counts ('137 want this')."""
    from cci_core.models import WaitlistEntry

    rows = db.scalars(select(WaitlistEntry).where(
        WaitlistEntry.creator_id == creator.id, WaitlistEntry.notified.is_(False))).all()
    by_topic: dict[str, set] = {}
    for r in rows:
        by_topic.setdefault(r.topic.strip().lower(), set()).add(r.email)
    cohorts = [{"topic": t, "people_waiting": len(emails)} for t, emails in by_topic.items()]
    cohorts.sort(key=lambda c: c["people_waiting"], reverse=True)
    return cohorts[:50]


@router.get("/api/{handle}/popular")
def most_asked(creator: Creator = Depends(get_creator),
               db: Session = Depends(get_db)) -> list[dict]:
    """Most-asked questions — so a fan who doesn't know what to type has a starting
    point instead of a blank box."""
    from cci_core.models import DemandTopic

    rows = db.scalars(
        select(DemandTopic).where(DemandTopic.creator_id == creator.id)
        .order_by(DemandTopic.opportunity_score.desc().nullslast(),
                  (DemandTopic.search_count + DemandTopic.comment_count).desc())
        .limit(8)).all()
    out = []
    for t in rows:
        question = (t.audience_language[0] if t.audience_language else t.label)
        out.append({"question": question, "label": t.label})
    return out


@router.get("/api/{handle}/start-here")
def start_here(creator: Creator = Depends(get_creator),
               db: Session = Depends(get_db)) -> dict:
    """Curated entry paths for a first-time visitor who doesn't know what to type:
    a couple of popular questions + the strongest topics to browse."""
    from collections import Counter

    from cci_core.models import DemandTopic, Enrichment, Post

    cards = db.scalars(
        select(DemandTopic).where(DemandTopic.creator_id == creator.id)
        .order_by(DemandTopic.opportunity_score.desc().nullslast()).limit(3)).all()
    paths = [{"label": f"Ask: {(c.audience_language[0] if c.audience_language else c.label)}",
              "query": (c.audience_language[0] if c.audience_language else c.label)}
             for c in cards]
    topic_rows = db.execute(
        select(Enrichment.topics).join(Post, Post.id == Enrichment.post_id)
        .where(Post.creator_id == creator.id, Post.status == "active")).all()
    counts: Counter = Counter()
    for (topics,) in topic_rows:
        for t in (topics or []):
            counts[str(t).strip()] += 1
    for topic, _ in counts.most_common(3):
        paths.append({"label": f"Explore: {topic}", "query": topic})
    return {"paths": paths[:5],
            "hint": "Or just ask in your own words — I search everything they've posted."}


@router.get("/api/{handle}/topics")
def browse_topics(creator: Creator = Depends(get_creator),
                  db: Session = Depends(get_db)) -> list[dict]:
    """Topic browsing — the archive's subjects, for fans who'd rather explore."""
    from collections import Counter

    from cci_core.models import Enrichment, Post

    rows = db.execute(
        select(Enrichment.topics).join(Post, Post.id == Enrichment.post_id)
        .where(Post.creator_id == creator.id, Post.status == "active")).all()
    counts: Counter = Counter()
    for (topics,) in rows:
        for t in (topics or []):
            counts[str(t).strip().lower()] += 1
    return [{"topic": t, "posts": n} for t, n in counts.most_common(30)]


class FeedbackIn(BaseModel):
    answer_id: str
    helpful: bool


@router.post("/api/{handle}/feedback", dependencies=[Depends(rate_limit)])
def answer_feedback(body: FeedbackIn, creator: Creator = Depends(get_creator),
                    db: Session = Depends(get_db)) -> dict:
    """Outcome Memory: 'did this help?' — closes the outcome edge with the result,
    so Sift learns which answers actually work (not just what was asked)."""
    from cci_core.models import Outcome

    outcome = db.scalar(select(Outcome).where(
        Outcome.creator_id == creator.id, Outcome.answer_id == body.answer_id))
    if outcome is not None:
        outcome.stage = "resolved" if body.helpful else "unresolved"
        outcome.result = {**(outcome.result or {}), "helpful": body.helpful}
    events.track(db, "answer_feedback", creator.id, answer_id=body.answer_id,
                 helpful=body.helpful)
    return {"ok": True}


@router.get("/api/{handle}/buy/{product_id}")
def affiliate_redirect(product_id: str, creator: Creator = Depends(get_creator),
                       db: Session = Depends(get_db)):
    """Monetization hook: tracked redirect to the creator-approved affiliate link."""
    product = db.get(Product, product_id)
    if product is None or product.creator_id != creator.id or not product.approved:
        raise HTTPException(status_code=404, detail="product not found")
    if not product.affiliate_url:
        raise HTTPException(status_code=404, detail="no affiliate link")
    events.track(db, events.AFFILIATE_CLICK, creator.id, product_id=product_id)
    db.commit()  # make sure the click is recorded before we hand off
    return RedirectResponse(product.affiliate_url, status_code=302)


@router.get("/api/{handle}/posts/{post_id}")
def get_post(post_id: str, creator: Creator = Depends(get_creator),
             db: Session = Depends(get_db)) -> dict:
    post = db.get(Post, post_id)
    if post is None or post.creator_id != creator.id:
        raise HTTPException(status_code=404, detail="post not found")
    return {
        "post_id": post.id, "type": post.type, "caption": post.caption,
        "permalink": post.permalink,
        "posted_at": post.posted_at.isoformat() if post.posted_at else None,
    }
