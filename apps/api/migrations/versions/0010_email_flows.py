"""Add email verification, password reset, and repo notification email fields."""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # users: email verification
    conn.execute(text("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS email_verified BOOL NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS email_verify_token TEXT,
        ADD COLUMN IF NOT EXISTS email_verify_expires_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS password_reset_token TEXT,
        ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMPTZ
    """))

    # Existing users (pre-migration) — treat as verified so they're not blocked.
    conn.execute(text("UPDATE users SET email_verified = TRUE WHERE email_verified = FALSE"))

    # repositories: per-repo email notifications
    conn.execute(text("""
        ALTER TABLE repositories
        ADD COLUMN IF NOT EXISTS notification_emails TEXT[] NOT NULL DEFAULT '{}',
        ADD COLUMN IF NOT EXISTS notify_email_on_complete BOOL NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS notify_email_on_fix_pr BOOL NOT NULL DEFAULT FALSE
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("""
        ALTER TABLE users
        DROP COLUMN IF EXISTS email_verified,
        DROP COLUMN IF EXISTS email_verify_token,
        DROP COLUMN IF EXISTS email_verify_expires_at,
        DROP COLUMN IF EXISTS password_reset_token,
        DROP COLUMN IF EXISTS password_reset_expires_at
    """))
    conn.execute(text("""
        ALTER TABLE repositories
        DROP COLUMN IF EXISTS notification_emails,
        DROP COLUMN IF EXISTS notify_email_on_complete,
        DROP COLUMN IF EXISTS notify_email_on_fix_pr
    """))
