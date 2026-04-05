"""Add finding_feedback table for tuning flywheel.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'feedback_signal_enum'
            ) THEN
                CREATE TYPE feedback_signal_enum AS ENUM (
                    'thumbs_up', 'thumbs_down', 'ignored', 'applied'
                );
            END IF;
        END $$;
    """))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS finding_feedback (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            finding_id  UUID        NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
            job_id      UUID        NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
            tenant_id   UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            signal      feedback_signal_enum NOT NULL,
            note        TEXT,
            feedback_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """))

    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_finding_feedback_finding_id
            ON finding_feedback (finding_id);
    """))

    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_finding_feedback_tenant_id
            ON finding_feedback (tenant_id, feedback_at DESC);
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS finding_feedback;"))
    conn.execute(sa.text("DROP TYPE IF EXISTS feedback_signal_enum;"))
