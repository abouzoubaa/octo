"""Add creators.email — delivery address for the weekly digest/briefing.

Additive + idempotent; nullable (operators can onboard without an email; the
digest transport falls back to logging when unset).

Revision ID: 0005_creator_email
Revises: 0004_pa_full_loop
Create Date: 2026-06-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_creator_email"
down_revision: str | Sequence[str] | None = "0004_pa_full_loop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE creators ADD COLUMN IF NOT EXISTS email VARCHAR(256)"))


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE creators DROP COLUMN IF EXISTS email"))
