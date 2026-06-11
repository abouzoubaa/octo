"""Core data model — every row is creator-scoped (multi-tenant ready from day one).

Design notes (docs/IMPLEMENTATION_PLAN.md §3):
- Deletion-first: deleting a post cascades to chunks/citations; stale citations kill trust.
- Pseudonymous audience data (GDPR): commenter identities are stored as salted hashes.
- Embedding model/version/dims are stored per chunk so an embedding swap is a planned
  re-embed job, never a mixed index.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Computed,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


# --------------------------------------------------------------------------- creators


class CreatorStatus(str, enum.Enum):
    onboarding = "onboarding"
    active = "active"
    paused = "paused"


class Creator(Base):
    __tablename__ = "creators"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    handle: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # /<handle>
    display_name: Mapped[str] = mapped_column(String(128))
    ig_user_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    yt_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[CreatorStatus] = mapped_column(
        Enum(CreatorStatus, native_enum=False), default=CreatorStatus.onboarding
    )
    niche: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    posts: Mapped[list[Post]] = relationship(back_populates="creator")


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"
    __table_args__ = (UniqueConstraint("creator_id", "platform"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(16))  # instagram | youtube
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ------------------------------------------------------------------------------ posts


class PostStatus(str, enum.Enum):
    active = "active"
    deleted = "deleted"  # creator deleted it on-platform → purge chunks, keep tombstone


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("creator_id", "platform", "external_id"),
        Index("ix_posts_creator_status", "creator_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(16))  # instagram | youtube
    external_id: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32))  # reel | image | carousel | video | short
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    permalink: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus, native_enum=False), default=PostStatus.active
    )
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # per-post comment-sync watermark (comment reads are cursor-paginated, no time filter)
    comment_sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_comment_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    creator: Mapped[Creator] = relationship(back_populates="posts")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # video | image | audio
    storage_key: Mapped[str] = mapped_column(Text)  # S3 object key
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    post_id: Mapped[str] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), unique=True
    )
    source: Mapped[str] = mapped_column(String(16))  # whisper | yt_caption
    text: Mapped[str] = mapped_column(Text)
    segments: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{start,end,text}]
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OcrText(Base):
    __tablename__ = "ocr_texts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    frame_ts: Mapped[float | None] = mapped_column(Float, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class Enrichment(Base):
    __tablename__ = "enrichments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    post_id: Mapped[str] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), unique=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    topics: Mapped[list | None] = mapped_column(JSON, nullable=True)
    keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    product_mentions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    location_mentions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ------------------------------------------------------------------------------ index


class ChunkSource(str, enum.Enum):
    caption = "caption"
    transcript = "transcript"
    ocr = "ocr"
    summary = "summary"


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_creator", "creator_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    source: Mapped[ChunkSource] = mapped_column(Enum(ChunkSource, native_enum=False))
    text: Mapped[str] = mapped_column(Text)
    start_ts: Mapped[float | None] = mapped_column(Float, nullable=True)  # transcript chunks
    embedding = mapped_column(Vector(), nullable=True)  # dims recorded per row
    # generated full-text column — the lexical half of hybrid retrieval
    tsv = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True), nullable=True
    )
    embed_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    embed_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    embed_dims: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    post: Mapped[Post] = relationship(back_populates="chunks")


# ------------------------------------------------------------------- audience signals


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint("creator_id", "external_id"),
        Index("ix_comments_creator_question", "creator_id", "is_question"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    post_id: Mapped[str | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str] = mapped_column(String(64))
    author_pseudonym: Mapped[str] = mapped_column(String(64))  # salted hash, never raw handle
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_question: Mapped[bool] = mapped_column(Boolean, default=False)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuerySource(str, enum.Enum):
    search = "search"
    dm = "dm"
    comment = "comment"


class Query(Base):
    __tablename__ = "queries"
    __table_args__ = (Index("ix_queries_creator_created", "creator_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    source: Mapped[QuerySource] = mapped_column(Enum(QuerySource, native_enum=False))
    text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_post_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnswerState(str, enum.Enum):
    answered = "answered"
    no_strong_answer = "no_strong_answer"


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    query_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{post_id, chunk_id, quote}]
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    state: Mapped[AnswerState] = mapped_column(Enum(AnswerState, native_enum=False))
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ------------------------------------------------------------------- comment-to-DM


class DmStatus(str, enum.Enum):
    pending_approval = "pending_approval"
    approved = "approved"
    sent = "sent"
    fallback = "fallback"  # low confidence → archive link only
    rejected = "rejected"
    failed = "failed"
    expired = "expired"  # outside the 7-day private-reply window


class DmJob(Base):
    __tablename__ = "dm_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    comment_id: Mapped[str] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), unique=True  # one reply per comment
    )
    status: Mapped[DmStatus] = mapped_column(
        Enum(DmStatus, native_enum=False), default=DmStatus.pending_approval
    )
    public_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    dm_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    deep_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# ------------------------------------------------------------------- Demand Radar


class DemandTopic(Base):
    __tablename__ = "demand_topics"
    __table_args__ = (Index("ix_demand_topics_creator_week", "creator_id", "week"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(256))
    week: Mapped[str] = mapped_column(String(10))  # ISO week, e.g. 2026-W24
    search_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    wow_change: Mapped[float | None] = mapped_column(Float, nullable=True)  # week-over-week %
    coverage: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {post_ids, gaps}
    audience_language: Mapped[list | None] = mapped_column(JSON, nullable=True)  # verbatims
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_products: Mapped[list | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(8), nullable=True)  # high|med|low
    creator_marked: Mapped[str | None] = mapped_column(String(16), nullable=True)  # useful|not|made
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ------------------------------------------------------------------- monetization


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(256))
    affiliate_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)  # creator-approved only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductLink(Base):
    __tablename__ = "product_links"
    __table_args__ = (UniqueConstraint("post_id", "product_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(16), default="enrichment")  # enrichment | manual


# ------------------------------------------------------------------- events & eval


class Event(Base):
    """Append-only event log — powers every metric in plan §8 from day one."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_creator_kind_ts", "creator_id", "kind", "ts"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))  # search|result_click|deeplink_open|dm_sent|...
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvalQuestion(Base):
    __tablename__ = "eval_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    expected_post_ids: Mapped[list] = mapped_column(JSON)  # [] ⇒ expected "no answer"
    holdout: Mapped[bool] = mapped_column(Boolean, default=False)  # citation gate uses these
    labelled_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    git_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    top3_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    citation_correctness: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_answer_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_questions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
