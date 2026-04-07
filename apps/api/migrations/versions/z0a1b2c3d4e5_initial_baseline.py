"""initial baseline schema (former docker init.sql full DDL)

Revision ID: z0a1b2c3d4e5
Revises:
Create Date: 2026-04-07

"""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
import sqlparse
from alembic import op

revision = "z0a1b2c3d4e5"
down_revision = None
branch_labels = None
depends_on = None


def _repo_root() -> Path:
    # apps/api/migrations/versions/<this file> -> parents[4] = repo root
    return Path(__file__).resolve().parents[4]


def upgrade() -> None:
    conn = op.get_bind()
    already = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'tenants')"
        )
    ).scalar()
    if already:
        # Legacy DB: schema was created by the old all-in-one docker-entrypoint init.sql
        return

    path = _repo_root() / "infra" / "db" / "baseline_schema.sql"
    sql = path.read_text(encoding="utf-8")
    for raw in sqlparse.split(sql):
        stmt = raw.strip()
        if not stmt:
            continue
        conn.execute(sa.text(stmt))


def downgrade() -> None:
    raise NotImplementedError(
        "Baseline downgrade would drop the entire public schema; restore from backup instead."
    )
