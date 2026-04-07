"""Add llm_provider TEXT column to analysis_jobs.

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
"""
from alembic import op
import sqlalchemy as sa

revision = "n4o5p6q7r8s9"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
        ALTER TABLE analysis_jobs
        ADD COLUMN IF NOT EXISTS llm_provider TEXT NOT NULL DEFAULT 'anthropic';
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE analysis_jobs DROP COLUMN IF EXISTS llm_provider;"))
