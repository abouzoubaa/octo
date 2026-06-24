"""Public audience API — no login wall (plan §3: built for the in-app browser).

Every search and click is logged as a demand signal: the query IS the asset.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_api.deps import get_creator
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


class SearchResponse(BaseModel):
    query: str
    results: list[ResultOut]
    answer: AnswerOut | None = None
    deep_link: str


@router.get("/api/{handle}/search", response_model=SearchResponse)
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
        card = generate_answer(db, creator.id, q)
        results = card.results
        if card.state == "answered":
            persisted = persist_answer(db, creator.id, card)
            answer_id = persisted.id
        answer_out = AnswerOut(
            state=card.state, text=card.text,
            citations=[CitationOut(**c) for c in card.citations],
            confidence=round(card.confidence, 3), answer_id=answer_id,
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
        products=[{"id": p.id, "name": p.name} for p in product_rows],
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
