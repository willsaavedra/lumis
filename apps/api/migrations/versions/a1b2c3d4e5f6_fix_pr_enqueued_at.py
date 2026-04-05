"""add fix_pr_enqueued_at to analysis_jobs

Revision ID: a1b2c3d4e5f6
Revises: 9b4c2e7f1a3d
Create Date: 2026-04-02

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "9b4c2e7f1a3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS fix_pr_url TEXT;"))
    conn.execute(sa.text(
        "ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS fix_pr_enqueued_at TIMESTAMPTZ;"
    ))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE analysis_jobs DROP COLUMN IF EXISTS fix_pr_enqueued_at;"))
