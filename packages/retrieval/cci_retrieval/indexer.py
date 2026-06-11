"""Index a post: chunk every text source, embed, store — and reindex/delete cleanly.

Stale citations kill trust (plan §4.3): deleting a post purges its chunks, and a
re-enrichment or embedding-model swap is a full, atomic replace per post.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cci_core.models import Chunk, Enrichment, OcrText, Post, PostStatus, Transcript
from cci_providers import get_embedding_provider
from cci_retrieval.chunking import RawChunk, chunk_caption, chunk_ocr, chunk_summary, chunk_transcript


def build_raw_chunks(session: Session, post: Post) -> list[RawChunk]:
    raw: list[RawChunk] = []
    if post.caption:
        raw += chunk_caption(post.caption)
    transcript = session.scalar(select(Transcript).where(Transcript.post_id == post.id))
    if transcript and transcript.segments:
        raw += chunk_transcript(transcript.segments)
    elif transcript and transcript.text:
        raw += [RawChunk("transcript", t) for t in [transcript.text] if t.strip()]
    ocr_rows = session.scalars(select(OcrText).where(OcrText.post_id == post.id)).all()
    if ocr_rows:
        raw += chunk_ocr([(o.text, o.frame_ts) for o in ocr_rows])
    enrichment = session.scalar(select(Enrichment).where(Enrichment.post_id == post.id))
    if enrichment and enrichment.summary:
        raw += chunk_summary(enrichment.summary)
    return raw


def index_post(session: Session, post: Post) -> int:
    """(Re)index one post atomically: purge old chunks, write fresh embedded ones."""
    session.execute(delete(Chunk).where(Chunk.post_id == post.id))
    if post.status == PostStatus.deleted:
        return 0

    raw = build_raw_chunks(session, post)
    if not raw:
        return 0

    provider = get_embedding_provider()
    vectors = provider.embed([c.text for c in raw])
    for rc, vec in zip(raw, vectors):
        session.add(
            Chunk(
                post_id=post.id,
                creator_id=post.creator_id,
                source=rc.source,
                text=rc.text,
                start_ts=rc.start_ts,
                embedding=vec,
                embed_model=provider.model,
                embed_version=provider.version,
                embed_dims=provider.dims,
            )
        )
    return len(raw)


def reindex_creator(session: Session, creator_id: str) -> int:
    """Planned re-embed job — e.g. after an embedding model/version swap."""
    posts = session.scalars(select(Post).where(Post.creator_id == creator_id)).all()
    total = 0
    for post in posts:
        total += index_post(session, post)
    return total


def purge_post(session: Session, post: Post) -> None:
    """Creator deleted the post on-platform: tombstone it and drop its index."""
    post.status = PostStatus.deleted
    session.execute(delete(Chunk).where(Chunk.post_id == post.id))
