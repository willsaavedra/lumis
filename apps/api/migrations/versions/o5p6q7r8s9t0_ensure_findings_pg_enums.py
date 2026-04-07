"""Ensure pillar_enum, severity_enum, dimension_enum exist (parity with infra/db/init.sql).

Databases created only via Alembic may lack these types; the agent then fails on INSERT into findings.

Revision ID: o5p6q7r8s9t0
Revises: o6p7q8r9s0t1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "o5p6q7r8s9t0"
down_revision = "o6p7q8r9s0t1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Idempotent: skip if type already exists (e.g. created by docker init.sql)
    stmts = [
        """
        DO $$ BEGIN
            CREATE TYPE pillar_enum AS ENUM ('metrics', 'logs', 'traces', 'iac', 'pipeline');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """,
        """
        DO $$ BEGIN
            CREATE TYPE severity_enum AS ENUM ('critical', 'warning', 'info');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """,
        """
        DO $$ BEGIN
            CREATE TYPE dimension_enum AS ENUM ('cost', 'snr', 'pipeline', 'compliance', 'coverage');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """,
    ]
    for sql in stmts:
        conn.execute(sa.text(sql))


def downgrade() -> None:
    # Do not drop types: columns may still reference them.
    pass
