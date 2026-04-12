"""Add notify_on_fix_pr to teams for Slack/Teams fix-PR notifications."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "teams",
        sa.Column(
            "notify_on_fix_pr",
            sa.Boolean(),
            nullable=False,
            server_default=text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("teams", "notify_on_fix_pr")
