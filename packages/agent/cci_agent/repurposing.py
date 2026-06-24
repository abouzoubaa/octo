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
