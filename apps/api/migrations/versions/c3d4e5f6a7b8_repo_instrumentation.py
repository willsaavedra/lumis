"""Add instrumentation column to repositories

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS instrumentation TEXT;"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE repositories DROP COLUMN IF EXISTS instrumentation;"
    ))
