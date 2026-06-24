"""Database bootstrap: extensions, schema, indexes.

v1 keeps migrations simple: idempotent create-from-metadata plus explicit
indexes. When the schema starts evolving under live data, graduate to Alembic.

WARNING — create_all() only issues CREATE TABLE IF NOT EXISTS; it NEVER runs
ALTER TABLE. New *columns* added to an already-existing table (e.g. agent-layer
additions like Comment.sentiment, DmJob.parent_job_id/turn, CreatorRules opt-in
flags, DemandTopic.state) will be MISSING on a database that was initialised
before the column existed, causing runtime "undefined column" errors. On a fresh
dev DB this is fine; on any persisted DB you must ALTER manually or adopt Alembic
(tracked in docs/ROADMAP.md §2.3). Tests drop+recreate, so they always see the
full schema.
"""
from sqlalchemy import text

from cci_core.db import get_engine
from cci_core.models import Base


def init_db() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # GIN index for the full-text half of hybrid search
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON chunks USING gin (tsv)"))
    print("database initialised ✔")
