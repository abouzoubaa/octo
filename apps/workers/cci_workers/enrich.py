"""Per-post pipeline: transcribe → OCR → LLM enrichment → index (plan §4.2–4.3)."""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from sqlalchemy import select

from cci_core.db import session_scope
from cci_core.models import (
    Enrichment, MediaAsset, OcrText, Post, Product, ProductLink, Transcript,
)
from cci_core.storage import fetch_media
from cci_providers import get_llm, get_ocr, get_transcriber
from cci_retrieval.indexer import index_post

log = logging.getLogger(__name__)

ENRICH_SYSTEM = """\
You enrich a creator's social post for a search index. Given the post text
(caption + transcript + on-screen text), return JSON:
{"summary": "2-3 sentence factual summary",
 "topics": ["..."], "keywords": ["..."],
 "product_mentions": [{"name": "...", "context": "..."}],
 "location_mentions": ["..."]}
Be specific and faithful; do not invent products or claims.\
"""


def process_post(post_id: str) -> dict:
    """Idempotent: safe to re-run; each stage skips if its output exists."""
    stats = {"transcribed": False, "ocr": 0, "enriched": False, "chunks": 0}
    with session_scope() as session:
        post = session.get(Post, post_id)
        if post is None:
            return stats
        media = session.scalar(
            select(MediaAsset).where(MediaAsset.post_id == post.id, MediaAsset.kind == "video")
        )
        if media is not None:
            local = _materialize(media.storage_key)
            try:
                stats["transcribed"] = _transcribe(session, post, local)
                stats["ocr"] = _ocr(session, post, local)
            finally:
                Path(local).unlink(missing_ok=True)
        stats["enriched"] = _enrich(session, post)
        stats["chunks"] = index_post(session, post)
    return stats


def _materialize(storage_key: str) -> str:
    data = fetch_media(storage_key)
    tmp = tempfile.NamedTemporaryFile(suffix=Path(storage_key).suffix or ".mp4", delete=False)
    tmp.write(data)
    tmp.close()
    return tmp.name


def _transcribe(session, post: Post, media_path: str) -> bool:
    if session.scalar(select(Transcript).where(Transcript.post_id == post.id)):
        return False
    result = get_transcriber().transcribe(media_path)
    if not result.text.strip():
        return False
    session.add(
        Transcript(
            post_id=post.id,
            source="whisper",
            text=result.text,
            segments=[{"start": s.start, "end": s.end, "text": s.text} for s in result.segments],
            quality=result.quality,
        )
    )
    return True


def _ocr(session, post: Post, media_path: str) -> int:
    if session.scalar(select(OcrText).where(OcrText.post_id == post.id)):
        return 0
    fragments = get_ocr().extract(media_path)
    for frag in fragments:
        session.add(
            OcrText(post_id=post.id, frame_ts=frag.frame_ts, text=frag.text,
                    confidence=frag.confidence)
        )
    return len(fragments)


def _enrich(session, post: Post) -> bool:
    if session.scalar(select(Enrichment).where(Enrichment.post_id == post.id)):
        return False
    parts = [post.caption or ""]
    transcript = session.scalar(select(Transcript).where(Transcript.post_id == post.id))
    if transcript:
        parts.append(f"Transcript: {transcript.text[:4000]}")
    ocr_rows = session.scalars(select(OcrText).where(OcrText.post_id == post.id)).all()
    if ocr_rows:
        parts.append("On-screen text: " + " · ".join(o.text for o in ocr_rows[:50]))
    content = "\n\n".join(p for p in parts if p.strip())
    if not content.strip():
        return False

    llm = get_llm()
    try:
        data = json.loads(llm.complete(ENRICH_SYSTEM, content, json_output=True, max_tokens=800))
    except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001 — enrichment is best-effort
        log.warning("enrichment failed for %s: %s", post.id, exc)
        return False

    session.add(
        Enrichment(
            post_id=post.id,
            summary=data.get("summary"),
            topics=data.get("topics"),
            keywords=data.get("keywords"),
            product_mentions=data.get("product_mentions"),
            location_mentions=data.get("location_mentions"),
            model=llm.name,
            version="1",
        )
    )
    _link_products(session, post, data.get("product_mentions") or [])
    return True


def _link_products(session, post: Post, mentions: list) -> None:
    """Map product mentions to creator-approved products (monetization hook, §4.2)."""
    if not mentions:
        return
    products = session.scalars(
        select(Product).where(Product.creator_id == post.creator_id, Product.approved.is_(True))
    ).all()
    for mention in mentions:
        name = (mention.get("name") or "").lower() if isinstance(mention, dict) else str(mention).lower()
        for product in products:
            if product.name.lower() in name or name in product.name.lower():
                exists = session.scalar(
                    select(ProductLink).where(
                        ProductLink.post_id == post.id, ProductLink.product_id == product.id
                    )
                )
                if not exists:
                    session.add(ProductLink(post_id=post.id, product_id=product.id))


def process_all_pending(creator_id: str) -> int:
    """Enqueue-style sweep: process every active post lacking chunks."""
    from cci_core.models import Chunk, PostStatus

    processed = 0
    with session_scope() as session:
        post_ids = [
            row[0]
            for row in session.execute(
                select(Post.id)
                .outerjoin(Chunk, Chunk.post_id == Post.id)
                .where(Post.creator_id == creator_id, Post.status == PostStatus.active)
                .group_by(Post.id)
                .having(~Post.id.in_(select(Chunk.post_id).distinct()))
            )
        ]
    for pid in post_ids:
        process_post(pid)
        processed += 1
    return processed
