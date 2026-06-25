"""Add platform_accounts.full_loop (per-account capability grant).

A TikTok account approved for the full loop (comments + messaging) is a per-account
property, not a per-platform one. Persisting it lets the connector be built per
account so capability checks (sync_native, DM dispatch) reflect the actual grant.
Additive + idempotent; defaults to False (archive).

Revision ID: 0004_pa_full_loop
Revises: 0003_pa_last_synced
Create Date: 2026-06-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_pa_full_loop"
down_revision: str | Sequence[str] | None = "0003_pa_last_synced"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE platform_accounts "
        "ADD COLUMN IF NOT EXISTS full_loop BOOLEAN NOT NULL DEFAULT FALSE"))


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE platform_accounts DROP COLUMN IF EXISTS full_loop"))
