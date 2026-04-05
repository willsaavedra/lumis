"""Add target_type column to finding_feedback (finding vs suggestion).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Create target enum
    conn.execute(sa.text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'feedback_target_enum'
            ) THEN
                CREATE TYPE feedback_target_enum AS ENUM ('finding', 'suggestion');
            END IF;
        END $$;
    """))

    # Add column with default 'finding' for all existing rows
    conn.execute(sa.text("""
        ALTER TABLE finding_feedback
        ADD COLUMN IF NOT EXISTS target_type feedback_target_enum NOT NULL DEFAULT 'finding';
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE finding_feedback DROP COLUMN IF EXISTS target_type;"))
    conn.execute(sa.text("DROP TYPE IF EXISTS feedback_target_enum;"))
