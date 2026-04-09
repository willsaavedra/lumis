"""Consolidated baseline — full schema from infra/db/baseline_schema.sql.

On a fresh database this creates every table, index, RLS policy and trigger.
On an existing database (tenants table already present) this is a no-op so
Alembic can stamp the revision without breaking anything.

Revision ID: 0001
Revises:
Create Date: 2026-04-09
"""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
import sqlparse
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def upgrade() -> None:
    conn = op.get_bind()

    already = conn.execute(
        sa.text(
            "SELECT EXISTS ("
            "  SELECT FROM information_schema.tables "
            "  WHERE table_schema = 'public' AND table_name = 'tenants'"
            ")"
        )
    ).scalar()

    if already:
        return

    sql = (_repo_root() / "infra" / "db" / "baseline_schema.sql").read_text("utf-8")
    for raw in sqlparse.split(sql):
        stmt = raw.strip()
        if not stmt:
            continue
        conn.execute(sa.text(stmt))


def downgrade() -> None:
    raise NotImplementedError(
        "Baseline downgrade would drop the entire schema — restore from backup."
    )
