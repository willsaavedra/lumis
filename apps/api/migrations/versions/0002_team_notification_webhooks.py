"""Add encrypted Slack/Teams webhook columns to teams.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("slack_webhook_encrypted", sa.LargeBinary(), nullable=True))
    op.add_column("teams", sa.Column("msteams_webhook_encrypted", sa.LargeBinary(), nullable=True))
    op.add_column(
        "teams",
        sa.Column(
            "notify_on_analysis_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("teams", "notify_on_analysis_complete")
    op.drop_column("teams", "msteams_webhook_encrypted")
    op.drop_column("teams", "slack_webhook_encrypted")
