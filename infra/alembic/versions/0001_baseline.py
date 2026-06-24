"""Baseline schema — adopts Alembic on the existing create_all project.

This migration materialises the full current schema from the SQLAlchemy metadata
(the same tables/indexes `cci-migrate` creates) plus the pgvector extension and
the chunks FTS index. From here on, schema changes are versioned migrations —
no more silent create_all column drift (see docs/ROADMAP.md §2.3).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from cci_core.models import Base

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind)
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON chunks USING gin (tsv)"))


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
