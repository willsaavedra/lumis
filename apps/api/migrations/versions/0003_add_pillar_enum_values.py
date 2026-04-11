"""Add missing pillar_enum values: compliance, cost, snr."""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE pillar_enum ADD VALUE IF NOT EXISTS 'compliance'")
    op.execute("ALTER TYPE pillar_enum ADD VALUE IF NOT EXISTS 'cost'")
    op.execute("ALTER TYPE pillar_enum ADD VALUE IF NOT EXISTS 'snr'")


def downgrade() -> None:
    pass
