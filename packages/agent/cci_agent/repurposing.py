"""Content repurposing (v2): multi-format repurposing + Sift & Shift, series builder.

Turns one piece into adaptations (carousel, X thread, newsletter, TikTok hooks),
keeping voice consistent and pulling from existing transcribed clips. Sift & Shift:
a topic covered only on YouTube becomes an IG carousel drafted from the transcript.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.agent_foundations import voice_prompt_block
from cci_core.models import DemandTopic, Post, Transcript
from cci_providers import get_llm

FORMATS = ("ig_carousel", "x_thread", "newsletter", "tiktok_hooks")

REPURPOSE_SYSTEM = """\
Adapt the creator's existing content into the requested format, keeping their
voice and using ONLY the supplied source text for facts. Return JSON:
{"format": "...", "content": "..."} — content shaped for the format (carousel =
numbered slides; x_thread = numbered tweets; newsletter = short sections;
tiktok_hooks = a list of hooks).\
"""


def repurpose(session: Session, post_id: str, target_format: str) -> dict:
    """Adapt one existing post into another format, voice-consistent."""
    if target_format not in FORMATS:
        raise ValueError(f"unknown format '{target_format}'")
    post = session.get(Post, post_id)
    if post is None:
        raise ValueError("post not found")
    transcript = session.scalar(select(Transcript).where(Transcript.post_id == post_id))
    source = "\n".join(filter(None, [post.caption, transcript.text if transcript else None]))
    voice = voice_prompt_block(session, post.creator_id)
    try:
        data = json.loads(get_llm().complete(
            REPURPOSE_SYSTEM,
            f"Target format: {target_format}\n\nSource:\n{source[:4000]}\n\n{voice}",
            json_output=True, max_tokens=900))
    except Exception:  # noqa: BLE001
        data = {"format": target_format, "content": source[:500]}
    data["source_post_id"] = post_id
    return data


def sift_and_shift(session: Session, creator_id: str, target_format: str = "ig_carousel",
                   *, limit: int = 5) -> list[dict]:
    """Find YouTube topics NOT already covered on Instagram and draft them for IG from
    the transcript — a content-migration opportunity. Capped to `limit` posts to bound
    LLM cost (one generation per migrated post)."""
    yt_posts = session.scalars(
        select(Post).where(Post.creator_id == creator_id, Post.platform == "youtube")
    ).all()
    # cheap "already on IG?" check: lexical overlap of the YT title against IG captions
    ig_text = " ".join(
        (c or "").lower() for c in session.scalars(
            select(Post.caption).where(Post.creator_id == creator_id,
                                       Post.platform == "instagram"))
    )
    drafts = []
    for post in yt_posts:
        if len(drafts) >= limit:
            break
        transcript = session.scalar(select(Transcript).where(Transcript.post_id == post.id))
        if transcript is None:
            continue
        title_words = {w for w in (post.caption or "").lower().split() if len(w) > 5}
        if title_words and sum(1 for w in title_words if w in ig_text) / len(title_words) > 0.5:
            continue  # topic already well covered on Instagram — skip migration
        adapted = repurpose(session, post.id, target_format)
        adapted["migrated_from"] = "youtube"
        drafts.append(adapted)
    return drafts


def sift_and_shift_opportunities(session: Session, creator_id: str,
                                 target_platform: str = "tiktok") -> list[dict]:
    """The flagship cross-platform workflow: find canonical answers the creator has
    on SOME platform but NOT on `target_platform`, where there's audience demand —
    then offer a platform-native draft grounded in the existing source.

    'Your audience asks this on TikTok, but you only answered it on YouTube. Here's a
    TikTok script grounded in that video.'
    """
    from cci_agent.canonical import variants_of
    from cci_core.models import CanonicalContent

    # load demand once (loop-invariant) instead of per canonical
    demand_words = [
        {w for w in (d.label or "").lower().split() if len(w) > 3}
        for d in session.scalars(
            select(DemandTopic).where(DemandTopic.creator_id == creator_id))]

    opportunities = []
    for c in session.scalars(
            select(CanonicalContent).where(CanonicalContent.creator_id == creator_id)):
        variants = variants_of(session, c.id)
        platforms = {v.platform for v in variants}
        if target_platform in platforms or not platforms:
            continue  # already on the target, or nothing to migrate from
        # a source variant with substantive material (prefer one with a transcript)
        source = max(variants, key=lambda v: len(v.caption or ""))
        for v in variants:
            if session.scalar(select(Transcript).where(Transcript.post_id == v.id)):
                source = v
                break
        # is there demand for this topic? (any demand cluster overlapping the title)
        words = {w for w in (c.title or "").lower().split() if len(w) > 3}
        has_demand = any(words & dw for dw in demand_words)
        opportunities.append({
            "canonical_id": c.id, "title": c.title,
            "source_platform": source.platform, "source_post_id": source.id,
            "target_platform": target_platform,
            "covered_on": sorted(platforms),
            "has_demand": has_demand,
        })
    # demand-backed migrations first
    opportunities.sort(key=lambda o: not o["has_demand"])
    return opportunities


def draft_shift(session: Session, source_post_id: str, target_platform: str,
                persist: bool = True) -> dict:
    """Generate the platform-native draft for a Sift & Shift opportunity, grounded in
    the source post (e.g. a YouTube transcript → a TikTok script), and persist it into
    the creator's Drafts so the migration becomes an actionable, editable brief."""
    from cci_core.models import ContentDraft, Post

    fmt = {"tiktok": "tiktok_hooks", "instagram": "ig_carousel",
           "youtube": "newsletter"}.get(target_platform, "tiktok_hooks")
    adapted = repurpose(session, source_post_id, fmt)
    adapted["target_platform"] = target_platform
    adapted["migrated"] = True

    if persist:
        post = session.get(Post, source_post_id)
        # tiktok_hooks → a list of hooks; other formats → a single content block
        content = adapted.get("content")
        hooks = content if isinstance(content, list) else None
        script = content if isinstance(content, str) else None
        draft = ContentDraft(
            creator_id=post.creator_id,
            title=f"{target_platform.title()} version: {(post.caption or 'migrated post')[:200]}"[:256],
            brief={"migrated_from": source_post_id, "source_platform": post.platform,
                   "target_platform": target_platform, "format": fmt},
            hooks=hooks,
            script=script,
            source_post_ids=[source_post_id],
            status="draft",
        )
        session.add(draft)
        session.flush()
        adapted["draft_id"] = draft.id
    return adapted


def build_series(session: Session, creator_id: str, topic: DemandTopic) -> dict:
    """When a topic draws repeated demand, propose a planned arc: parts, FAQ, DM
    follow-up, offer tie-in."""
    try:
        data = json.loads(get_llm().complete(
            "Propose a content series arc for a recurring audience topic. JSON: "
            "{\"parts\": [\"part 1 …\", \"part 2 …\"], \"faq_post\": \"…\", "
            "\"dm_followup\": \"…\", \"offer_tie_in\": \"…\"}.",
            f"Topic: {topic.label}\nAudience asks: {topic.audience_language or []}",
            json_output=True, max_tokens=500))
    except Exception:  # noqa: BLE001
        data = {"parts": [topic.label], "faq_post": "", "dm_followup": "", "offer_tie_in": ""}
    data["topic_id"] = topic.id
    return data
