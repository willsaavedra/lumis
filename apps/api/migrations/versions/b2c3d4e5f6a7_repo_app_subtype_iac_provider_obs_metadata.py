"""Add app_subtype, iac_provider, obs_metadata to repositories

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(
        "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS app_subtype TEXT;"
    ))
    conn.execute(sa.text(
        "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS iac_provider TEXT;"
    ))
    conn.execute(sa.text(
        "ALTER TABLE repositories ADD COLUMN IF NOT EXISTS obs_metadata JSONB;"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE repositories DROP COLUMN IF EXISTS obs_metadata;"))
    conn.execute(sa.text("ALTER TABLE repositories DROP COLUMN IF EXISTS iac_provider;"))
    conn.execute(sa.text("ALTER TABLE repositories DROP COLUMN IF EXISTS app_subtype;"))
