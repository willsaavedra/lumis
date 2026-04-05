"""add context to analysis_type_enum

Revision ID: 7f3a1b9c2d4e
Revises: 4e92a0be20c0
Create Date: 2026-04-02

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '7f3a1b9c2d4e'
down_revision = '4e92a0be20c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TYPE analysis_type_enum ADD VALUE IF NOT EXISTS 'context'"))


def downgrade() -> None:
    # Postgres doesn't support removing enum values; this is a no-op
    pass
