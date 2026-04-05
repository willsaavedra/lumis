"""Tenant extra_balance_usd, analysis_jobs billing_reservation, wallet_credited event.

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "l2m3n4o5p6q7"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
        ALTER TABLE tenants
        ADD COLUMN IF NOT EXISTS extra_balance_usd NUMERIC(12, 2) NOT NULL DEFAULT 0;
        """
        )
    )

    conn.execute(
        sa.text(
            """
        ALTER TABLE analysis_jobs
        ADD COLUMN IF NOT EXISTS billing_reservation JSONB;
        """
        )
    )

    # Extend billing_event_type_enum
    conn.execute(
        sa.text(
            """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum e
                JOIN pg_type t ON e.enumtypid = t.oid
                WHERE t.typname = 'billing_event_type_enum' AND e.enumlabel = 'wallet_credited'
            ) THEN
                ALTER TYPE billing_event_type_enum ADD VALUE 'wallet_credited';
            END IF;
        END $$;
        """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE analysis_jobs DROP COLUMN IF EXISTS billing_reservation;"))
    conn.execute(sa.text("ALTER TABLE tenants DROP COLUMN IF EXISTS extra_balance_usd;"))
    # PostgreSQL cannot remove enum values safely — leave wallet_credited in place
