"""add repo context columns and vendor_connections table

Revision ID: 4e92a0be20c0
Revises:
Create Date: 2026-04-02

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '4e92a0be20c0'
down_revision = 'z0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Create enum types (raw DDL to avoid SQLAlchemy double-create issues)
    conn.execute(sa.text("CREATE TYPE repo_type_enum AS ENUM ('app', 'iac', 'library', 'monorepo')"))
    conn.execute(sa.text("CREATE TYPE obs_backend_enum AS ENUM ('datadog', 'grafana', 'prometheus', 'dynatrace', 'splunk')"))
    conn.execute(sa.text("CREATE TYPE vendor_enum AS ENUM ('datadog', 'grafana', 'prometheus', 'dynatrace', 'splunk')"))

    # Add new columns to repositories
    conn.execute(sa.text("ALTER TABLE repositories ADD COLUMN repo_type repo_type_enum"))
    conn.execute(sa.text("ALTER TABLE repositories ADD COLUMN language TEXT"))
    conn.execute(sa.text("ALTER TABLE repositories ADD COLUMN observability_backend obs_backend_enum"))
    conn.execute(sa.text("ALTER TABLE repositories ADD COLUMN context_summary TEXT"))

    # Create vendor_connections table
    conn.execute(sa.text("""
        CREATE TABLE vendor_connections (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            vendor vendor_enum NOT NULL,
            display_name TEXT,
            api_key TEXT,
            api_url TEXT,
            extra_config JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS vendor_connections"))
    conn.execute(sa.text("ALTER TABLE repositories DROP COLUMN IF EXISTS context_summary"))
    conn.execute(sa.text("ALTER TABLE repositories DROP COLUMN IF EXISTS observability_backend"))
    conn.execute(sa.text("ALTER TABLE repositories DROP COLUMN IF EXISTS language"))
    conn.execute(sa.text("ALTER TABLE repositories DROP COLUMN IF EXISTS repo_type"))
    conn.execute(sa.text("DROP TYPE IF EXISTS vendor_enum"))
    conn.execute(sa.text("DROP TYPE IF EXISTS obs_backend_enum"))
    conn.execute(sa.text("DROP TYPE IF EXISTS repo_type_enum"))
