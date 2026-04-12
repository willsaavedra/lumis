"""Add fix_pr_error column to analysis_jobs."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("fix_pr_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_jobs", "fix_pr_error")
