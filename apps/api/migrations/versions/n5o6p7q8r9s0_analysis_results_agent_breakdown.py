"""Add agent_breakdown JSONB to analysis_results (TS multi-agent stats).

Revision ID: n5o6p7q8r9s0
Revises: m3n4o5p6q7r8

Note: Broader TS-compat DDL (findings TEXT columns, enum drops) lives in
infra/migrations/005_ts_agent_compat.sql and may still be applied manually
on databases that predate those changes.
"""
from alembic import op
import sqlalchemy as sa

revision = "n5o6p7q8r9s0"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
        ALTER TABLE analysis_results
        ADD COLUMN IF NOT EXISTS agent_breakdown JSONB;
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE analysis_results DROP COLUMN IF EXISTS agent_breakdown;"))
