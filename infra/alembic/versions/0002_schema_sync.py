"""Catch-up sync: ensure all current columns/tables exist (idempotent).

The 0001 baseline materialised the schema as it was THEN; many agent + cross-
platform waves added columns to existing tables and new tables since. create_all
never ALTERs, so a database already stamped at 0001 would be missing those columns
(radar/canonical writes would fail). This migration converges ANY database to the
current model: new tables via create_all (IF NOT EXISTS), and every column on the
core mutable tables via ADD COLUMN IF NOT EXISTS — safe to run on a fresh DB too.

Revision ID: 0002_schema_sync
Revises: 0001_baseline
Create Date: 2026-06-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from cci_core.models import Base

revision: str = "0002_schema_sync"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# tables whose columns were extended after the baseline (skip generated/vector cols,
# which only live on `chunks` and are handled by create_all on first creation)
_SYNC_TABLES = (
    "posts", "comments", "demand_topics", "dm_jobs", "creator_rules", "oauth_tokens",
    "answers", "queries", "outcomes",
)
_SKIP_COLS = {"tsv", "embedding"}  # Computed / pgvector — never ADD-COLUMN-synced


def _add_missing_columns(bind) -> None:
    dialect = postgresql.dialect()
    for table_name in _SYNC_TABLES:
        table = Base.metadata.tables.get(table_name)
        if table is None:
            continue
        for col in table.columns:
            if col.name in _SKIP_COLS or col.computed is not None:
                continue
            coltype = col.type.compile(dialect=dialect)
            bind.execute(sa.text(
                f'ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS "{col.name}" {coltype}'))


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    # new tables added since the baseline (create_all is CREATE … IF NOT EXISTS)
    Base.metadata.create_all(bind)
    # new columns on pre-existing tables
    _add_missing_columns(bind)
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON chunks USING gin (tsv)"))


def downgrade() -> None:
    # additive, non-destructive sync — no-op downgrade
    pass
