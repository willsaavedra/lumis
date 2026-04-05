"""Add crossrun_summary JSONB to analysis_results for resolved/new/persisting metrics.

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
"""
from alembic import op
import sqlalchemy as sa

revision = "m3n4o5p6q7r8"
down_revision = "l2m3n4o5p6q7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
        ALTER TABLE analysis_results
        ADD COLUMN IF NOT EXISTS crossrun_summary JSONB;
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE analysis_results DROP COLUMN IF EXISTS crossrun_summary;"))
