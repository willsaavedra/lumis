"""Add previous_job_id to analysis_results for cross-run diff.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        ALTER TABLE analysis_results
        ADD COLUMN IF NOT EXISTS previous_job_id UUID
            REFERENCES analysis_jobs(id) ON DELETE SET NULL;
    """))
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_analysis_results_previous_job_id
            ON analysis_results (previous_job_id);
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_analysis_results_previous_job_id;"))
    conn.execute(sa.text("ALTER TABLE analysis_results DROP COLUMN IF EXISTS previous_job_id;"))
