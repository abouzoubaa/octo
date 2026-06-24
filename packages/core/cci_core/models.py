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
    sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)  # v2: anxiety|confusion|...
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
    # one creator-initiated reply per comment (unique); NULL for agentic follow-up
    # turns, which are re-opened by the fan's reply, not creator-initiated
    comment_id: Mapped[str | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), unique=True, nullable=True
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
    # agentic DM (v2): multi-turn threading within Meta's one-message/7-day window
    parent_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    turn: Mapped[int] = mapped_column(Integer, default=0)


# ------------------------------------------------------------------- Demand Radar


class DemandState(str, enum.Enum):
    """Lifecycle of a 'useful' demand item — the agent moves it through these."""

    new = "new"  # surfaced, creator hasn't triaged
    idea = "idea"  # creator marked it worth making
    drafting = "drafting"  # a content brief/draft exists
    published = "published"  # the creator shipped the post answering it
    loop_closed = "loop_closed"  # original askers notified (Loop-Closer)
    dismissed = "dismissed"  # creator marked not useful


# valid forward transitions for the demand-item state machine
DEMAND_TRANSITIONS: dict[DemandState, set[DemandState]] = {
    DemandState.new: {DemandState.idea, DemandState.dismissed},
    DemandState.idea: {DemandState.drafting, DemandState.dismissed},
    DemandState.drafting: {DemandState.published, DemandState.idea},
    DemandState.published: {DemandState.loop_closed},
    DemandState.loop_closed: set(),
    DemandState.dismissed: {DemandState.idea},
}


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
    # --- agent layer: lifecycle state machine (Idea → Drafting → Published → Loop-closed) ---
    state: Mapped[DemandState] = mapped_column(
        Enum(DemandState, native_enum=False), default=DemandState.new
    )
    published_post_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    state_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # the askers behind this cluster — for Loop-Closer (pseudonymous comment ids)
    asker_comment_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
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


# =====================================================================================
# AGENT LAYER — foundations the proactive features learn from (Sift agent roadmap §0)
# =====================================================================================


class Outcome(Base):
    """The outcome edge of the loop: who asked → what was served → what the creator
    did → what happened next. Lets the agent answer 'did it work?' and close loops.

    One row per traceable demand interaction; enriched as the interaction progresses.
    """

    __tablename__ = "outcomes"
    __table_args__ = (Index("ix_outcomes_creator_stage", "creator_id", "stage"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    # the asking side
    source: Mapped[str] = mapped_column(String(16))  # search | comment | dm
    query_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    comment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    demand_topic_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    asker_pseudonym: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # what was served
    answer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    served_state: Mapped[str | None] = mapped_column(String(24), nullable=True)  # answered|no_answer
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # what the creator did
    creator_action: Mapped[str | None] = mapped_column(String(32), nullable=True)  # approved_dm|made_post|...
    # what happened next (the measured edge)
    stage: Mapped[str] = mapped_column(String(24), default="served")  # served|acted|clicked|converted|closed
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {clicked, opened, converted, ...}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoiceExample(Base):
    """Voice memory: approved replies/hooks and the creator's edits to drafts, so
    generated content stays on-voice and improves over time. Few-shot fuel for every
    drafting feature; never invents claims (correctness stays a retrieval concern).
    """

    __tablename__ = "voice_examples"
    __table_args__ = (Index("ix_voice_examples_creator_kind", "creator_id", "kind"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))  # reply | hook | caption | dm | draft_edit
    text: Mapped[str] = mapped_column(Text)  # the approved / final text
    prompt_context: Mapped[str | None] = mapped_column(Text, nullable=True)  # what it answered
    original_draft: Mapped[str | None] = mapped_column(Text, nullable=True)  # pre-edit (for draft_edit)
    source: Mapped[str] = mapped_column(String(16), default="approved")  # approved | edit | seed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Offer(Base):
    """Offer-awareness: the creator tags current products/offers/campaigns so Sift
    routes every CTA and affiliate suggestion to the right one automatically.
    An Offer may wrap a Product (affiliate) or stand alone (course, coaching, launch).
    """

    __tablename__ = "offers"
    __table_args__ = (Index("ix_offers_creator_active", "creator_id", "active"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(24))  # product | course | coaching | newsletter | launch
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_id: Mapped[str | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    topics: Mapped[list | None] = mapped_column(JSON, nullable=True)  # topics this offer serves
    priority: Mapped[int] = mapped_column(Integer, default=0)  # higher wins when several match
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # current campaign?
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreatorRules(Base):
    """Rules & preferences: the business rules the agent operates under — tone, taboo
    topics, what must escalate to a human, and monetization priorities. One row per
    creator (the agent's operating contract).
    """

    __tablename__ = "creator_rules"

    creator_id: Mapped[str] = mapped_column(
        ForeignKey("creators.id", ondelete="CASCADE"), primary_key=True
    )
    tone: Mapped[str | None] = mapped_column(Text, nullable=True)  # voice/tone description
    taboo_topics: Mapped[list | None] = mapped_column(JSON, nullable=True)  # never engage
    escalate_topics: Mapped[list | None] = mapped_column(JSON, nullable=True)  # always human-review
    monetization_priority: Mapped[str | None] = mapped_column(
        String(24), nullable=True
    )  # affiliate | course | newsletter | none
    auto_approve_types: Mapped[list | None] = mapped_column(
        JSON, nullable=True
    )  # intent types pre-cleared for automation (still gated by eval)
    # v3 opt-ins (default off — aggregate/anonymised only when enabled)
    allow_benchmarking: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_competitor_radar: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# =====================================================================================
# AGENT LAYER — v1.5 "assist" features (content production, inbox, monetization)
# =====================================================================================


class ContentDraft(Base):
    """A content brief + draft (script/hooks) generated from a demand cluster.

    Grounded in the creator's own content (cited source posts) and the audience's
    literal phrasing; the creator edits/approves — never auto-published.
    """

    __tablename__ = "content_drafts"
    __table_args__ = (Index("ix_content_drafts_creator", "creator_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    demand_topic_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(256))
    brief: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {phrasing, gaps, cta, sources}
    hooks: Mapped[list | None] = mapped_column(JSON, nullable=True)  # candidate hook lines
    script: Mapped[str | None] = mapped_column(Text, nullable=True)  # reel/video script
    cta: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_post_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # grounding citations
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|approved|published
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WaitlistEntry(Base):
    """No-answer waitlist: when retrieval is weak, capture a lead who wants a
    heads-up when the creator covers the topic. Validates demand + feeds the gap map.
    """

    __tablename__ = "waitlist_entries"
    __table_args__ = (Index("ix_waitlist_creator_notified", "creator_id", "notified"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(256))
    topic: Mapped[str] = mapped_column(Text)  # the question that had no strong answer
    demand_topic_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Playbook(Base):
    """Saved playbook: 'when I get this kind of question, do this' — a reusable
    template for comments, DMs, and follow-ups so recurring situations are consistent.
    """

    __tablename__ = "playbooks"
    __table_args__ = (Index("ix_playbooks_creator", "creator_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    trigger_keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)  # match by intent label
    public_reply_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    dm_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# =====================================================================================
# AGENT LAYER — v2 "agent" features (engagement, intelligence, cross-platform)
# =====================================================================================


class DeferredItem(Base):
    """'Not now, but…' queue: a valid question the creator defers ('remind me in 6
    weeks — launching then'). Sift holds it, drafts when the time comes, and can
    re-contact the asker within compliant limits."""

    __tablename__ = "deferred_items"
    __table_args__ = (Index("ix_deferred_creator_due", "creator_id", "remind_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    comment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    demand_topic_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="waiting")  # waiting|surfaced|done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExternalSignal(Base):
    """Cross-platform demand synthesis (v2): questions from beyond Instagram —
    newsletter replies (a BCC address), forwarded DMs, transcribed podcast comments.
    Topic-level only; never individual cross-platform identity matching (GDPR)."""

    __tablename__ = "external_signals"
    __table_args__ = (Index("ix_external_signals_creator_platform", "creator_id", "platform"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(24))  # newsletter | podcast | youtube | dm_forward
    text: Mapped[str] = mapped_column(Text)
    is_question: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# =====================================================================================
# AGENT LAYER — v3 "scale" features (team, ecosystem, public API)
# =====================================================================================


class TeamRole(str, enum.Enum):
    owner = "owner"
    creator = "creator"  # can create/approve content
    analytics = "analytics"  # read-only VA
    contractor = "contractor"  # drafts only, needs approval


# capability gates per role (used by team.has_capability)
ROLE_CAPABILITIES: dict[TeamRole, set[str]] = {
    TeamRole.owner: {"read", "draft", "approve", "publish", "manage_team", "billing"},
    TeamRole.creator: {"read", "draft", "approve", "publish"},
    TeamRole.analytics: {"read"},
    TeamRole.contractor: {"read", "draft"},
}


class TeamMember(Base):
    """Team & role-based access (v3): owner, creator, analytics-only VA, contractor —
    so Sift scales as a solo creator becomes a team. Approval workflows + audit trail."""

    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("creator_id", "email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(256))
    role: Mapped[TeamRole] = mapped_column(Enum(TeamRole, native_enum=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiKey(Base):
    """Public API & dev ecosystem (v3 · scale): a hashed API key so third parties
    can build on Sift's intelligence layer. Scoped + revocable."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    prefix: Mapped[str] = mapped_column(String(12), index=True)  # lookup key (non-secret)
    key_hash: Mapped[str] = mapped_column(String(64))  # sha256 of the full key
    scopes: Mapped[list | None] = mapped_column(JSON, nullable=True)  # ["demand:read", ...]
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Audit trail for team actions (v3) — who did what, for accountability."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_creator_ts", "creator_id", "ts"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"))
    actor: Mapped[str] = mapped_column(String(256))  # team member email / "system"
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
