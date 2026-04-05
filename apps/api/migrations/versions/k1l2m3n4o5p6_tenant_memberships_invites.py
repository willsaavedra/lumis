"""Tenant memberships, invites, and profile completion flag.

Revision ID: k1l2m3n4o5p6
Revises: j0e1f2g3h4i5
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa

revision = "k1l2m3n4o5p6"
down_revision = "j0e1f2g3h4i5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'membership_role_enum') THEN
                CREATE TYPE membership_role_enum AS ENUM ('admin', 'operator', 'viewer');
            END IF;
        END $$;
    """
        )
    )

    conn.execute(
        sa.text(
            """
        CREATE TABLE IF NOT EXISTS tenant_memberships (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            role        membership_role_enum NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, tenant_id)
        );
    """
        )
    )
    conn.execute(
        sa.text(
            """
        CREATE INDEX IF NOT EXISTS ix_tenant_memberships_tenant_id
            ON tenant_memberships (tenant_id);
    """
        )
    )
    conn.execute(
        sa.text(
            """
        CREATE INDEX IF NOT EXISTS ix_tenant_memberships_user_id
            ON tenant_memberships (user_id);
    """
        )
    )

    conn.execute(
        sa.text(
            """
        CREATE TABLE IF NOT EXISTS tenant_invites (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            email               TEXT NOT NULL,
            role                membership_role_enum NOT NULL,
            token_hash          TEXT NOT NULL UNIQUE,
            invited_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
            expires_at          TIMESTAMPTZ NOT NULL,
            accepted_at         TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """
        )
    )
    conn.execute(
        sa.text(
            """
        CREATE INDEX IF NOT EXISTS ix_tenant_invites_tenant_email
            ON tenant_invites (tenant_id, lower(email));
    """
        )
    )

    conn.execute(
        sa.text(
            """
        ALTER TABLE tenants ADD COLUMN IF NOT EXISTS needs_profile_completion BOOLEAN NOT NULL DEFAULT FALSE;
    """
        )
    )
    # One-time prompt for workspaces created before tenant display name was required at signup.
    conn.execute(sa.text("UPDATE tenants SET needs_profile_completion = TRUE;"))

    # Backfill memberships from users (map legacy user_role_enum → membership_role_enum)
    conn.execute(
        sa.text(
            """
        INSERT INTO tenant_memberships (user_id, tenant_id, role)
        SELECT u.id,
               u.tenant_id,
               CASE u.role::text
                   WHEN 'owner' THEN 'admin'::membership_role_enum
                   WHEN 'admin' THEN 'admin'::membership_role_enum
                   WHEN 'member' THEN 'operator'::membership_role_enum
                   WHEN 'viewer' THEN 'viewer'::membership_role_enum
                   ELSE 'operator'::membership_role_enum
               END
        FROM users u
        ON CONFLICT (user_id, tenant_id) DO NOTHING;
    """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS tenant_invites;"))
    conn.execute(sa.text("DROP TABLE IF EXISTS tenant_memberships;"))
    conn.execute(sa.text("ALTER TABLE tenants DROP COLUMN IF EXISTS needs_profile_completion;"))
    conn.execute(sa.text("DROP TYPE IF EXISTS membership_role_enum;"))
