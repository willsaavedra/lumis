"""Add app_map to repositories, pending_questions/user_answers to analysis_jobs, awaiting_input status."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("repositories", sa.Column("app_map", JSONB, nullable=True))
    op.add_column("analysis_jobs", sa.Column("pending_questions", JSONB, nullable=True))
    op.add_column("analysis_jobs", sa.Column("user_answers", JSONB, nullable=True))

    op.execute("""
        ALTER TYPE job_status_enum ADD VALUE IF NOT EXISTS 'awaiting_input'
    """)


def downgrade() -> None:
    op.drop_column("repositories", "app_map")
    op.drop_column("analysis_jobs", "pending_questions")
    op.drop_column("analysis_jobs", "user_answers")
