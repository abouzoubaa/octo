"""Content production (v1.5): content briefs, draft generator, creator recall search.

The agent closes the gap between a demand signal and a finished post — the creator
becomes an editor, not a writer. Everything is grounded in the creator's own
content (cited source posts) and the audience's literal phrasing, and rewritten
into the creator's voice using voice memory. Never auto-published.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from cci_core.agent_foundations import best_offer_for_topics, get_rules, is_taboo, voice_prompt_block
from cci_core.models import ContentDraft, DemandTopic
from cci_providers import get_llm
from cci_retrieval.search import search

BRIEF_SYSTEM = """\
You write a one-page content brief for a creator from a cluster of real audience
questions and the creator's existing coverage. Return JSON:
{"angle": "the specific angle to take",
 "audience_phrasing": ["literal questions to echo in the hook"],
 "covers_gap": "what current content misses that this should answer",
 "cta": "a single clear call to action"}
Ground everything in the supplied material; invent nothing.\
"""

DRAFT_SYSTEM = """\
You draft a short-form video (reel) from a content brief, grounded ONLY in the
creator's supplied source passages and the audience's literal phrasing. Return JSON:
{"hooks": ["3 scroll-stopping opening lines, one liftable from a real question"],
 "script": "a 30-45s spoken script in short sentences",
 "caption": "a publish-ready caption",
 "cta": "the call to action"}
Match the creator's voice shown below. Never state facts not present in the
source passages — if unsure, keep it general. No medical/financial claims.\
"""


def generate_brief(session: Session, creator_id: str, topic: DemandTopic) -> dict:
    """One-page brief from a demand cluster: phrasing, gap, hook angle, CTA, sources."""
    verbatims = topic.audience_language or [topic.label]
    results = search(session, creator_id, max(verbatims, key=len), top_k=4)
    sources = [{"post_id": r.post_id, "permalink": r.permalink,
                "excerpt": (r.evidence[0].text[:200] if r.evidence else r.caption)}
               for r in results]
    context = (
        "Audience questions:\n" + "\n".join(f"- {v}" for v in verbatims)
        + "\n\nExisting coverage:\n"
        + ("\n".join(f"- {s['excerpt']}" for s in sources) or "- (no strong coverage yet)")
    )
    try:
        data = json.loads(get_llm().complete(BRIEF_SYSTEM, context, json_output=True, max_tokens=500))
    except Exception:  # noqa: BLE001
        data = {"angle": topic.recommendation or topic.label,
                "audience_phrasing": verbatims[:3], "covers_gap": "", "cta": ""}
    data["sources"] = sources
    return data


def generate_draft(session: Session, creator_id: str, topic: DemandTopic,
                   persist: bool = True) -> ContentDraft:
    """Reel script + hooks grounded in the creator's content and audience's words,
    rewritten into the creator's voice. Returns a ContentDraft (status='draft')."""
    brief = generate_brief(session, creator_id, topic)
    voice = voice_prompt_block(session, creator_id, kind="hook")
    offer = best_offer_for_topics(session, creator_id, topic.audience_language or [topic.label])

    source_excerpts = "\n".join(f"- {s['excerpt']}" for s in brief.get("sources", []) if s.get("excerpt"))
    user = (
        f"Brief angle: {brief.get('angle')}\n"
        f"Audience phrasing: {brief.get('audience_phrasing')}\n"
        f"Gap to close: {brief.get('covers_gap')}\n\n"
        f"Source passages (the only facts you may use):\n{source_excerpts or '- (general knowledge only; stay generic)'}\n\n"
        f"{voice}\n"
        + (f"\nWeave in this current offer as the CTA if natural: {offer.name} ({offer.url})" if offer else "")
    )
    try:
        data = json.loads(get_llm().complete(DRAFT_SYSTEM, user, json_output=True, max_tokens=800))
    except Exception:  # noqa: BLE001
        data = {"hooks": brief.get("audience_phrasing", [])[:3], "script": "", "caption": "",
                "cta": brief.get("cta", "")}

    draft = ContentDraft(
        creator_id=creator_id,
        demand_topic_id=topic.id,
        title=(brief.get("angle") or topic.label)[:256],
        brief=brief,
        hooks=data.get("hooks"),
        script=data.get("script"),
        cta=data.get("cta") or (offer.url if offer else None),
        source_post_ids=[s["post_id"] for s in brief.get("sources", [])],
        status="draft",
    )
    if persist:
        session.add(draft)
        session.flush()
    return draft


def creator_recall(session: Session, creator_id: str, query: str, top_k: int = 5) -> list[dict]:
    """Creator-only 'where did I say that?' — returns the exact sentence, link, and
    reuse ideas. Reuses the retrieval layer; no generation of new claims."""
    rules = get_rules(session, creator_id)
    if is_taboo(rules, query):
        return []
    results = search(session, creator_id, query, top_k=top_k)
    return [{
        "post_id": r.post_id,
        "permalink": r.permalink,
        "posted_at": r.posted_at,
        "sentence": (r.evidence[0].text if r.evidence else r.caption),
        "source": (r.evidence[0].source if r.evidence else "caption"),
    } for r in results]
