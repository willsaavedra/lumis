"""Add needs_onboarding column to tenants."""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("""
        ALTER TABLE tenants
        ADD COLUMN IF NOT EXISTS needs_onboarding BOOL NOT NULL DEFAULT FALSE
    """))
    # All existing tenants are grandfathered — already past onboarding.
    conn.execute(text("""
        UPDATE tenants SET needs_onboarding = FALSE
    """))


def downgrade() -> None:
    op.get_bind().execute(text("ALTER TABLE tenants DROP COLUMN IF EXISTS needs_onboarding"))
