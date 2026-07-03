"""Add platform_accounts.last_synced_at (per-connector sync timestamp).

sync_native stamps this on each run so the dashboard can show "last synced" per
connector. Additive + idempotent (ADD COLUMN IF NOT EXISTS), safe on a fresh DB too.

Revision ID: 0003_pa_last_synced
Revises: 0002_schema_sync
Create Date: 2026-06-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_pa_last_synced"
down_revision: str | Sequence[str] | None = "0002_schema_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE platform_accounts "
        "ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ"))


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE platform_accounts DROP COLUMN IF EXISTS last_synced_at"))
