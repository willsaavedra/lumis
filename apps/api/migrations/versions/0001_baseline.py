"""Consolidated baseline — full schema from infra/db/baseline_schema.sql.

On a fresh database this creates every table, index, RLS policy and trigger.
On an existing database (tenants table already present) this is a no-op so
Alembic can stamp the revision without breaking anything.

Revision ID: 0001
Revises:
Create Date: 2026-04-09
"""
from __future__ import annotations

import re
from pathlib import Path

import sqlalchemy as sa
import sqlparse
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_PGVECTOR_RE = re.compile(
    r"--\s*__PGVECTOR_START__.*?--\s*__PGVECTOR_END__",
    re.DOTALL,
)


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

    full_sql = (_repo_root() / "infra" / "db" / "baseline_schema.sql").read_text("utf-8")

    pgvector_block = _PGVECTOR_RE.search(full_sql)
    pgvector_sql = pgvector_block.group(0) if pgvector_block else ""
    core_sql = _PGVECTOR_RE.sub("", full_sql)

    for raw in sqlparse.split(core_sql):
        stmt = raw.strip()
        if not stmt:
            continue
        stripped = re.sub(r"--[^\n]*", "", stmt).strip()
        if not stripped:
            continue
        conn.execute(sa.text(stmt))

    if pgvector_sql:
        has_vector = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM pg_available_extensions WHERE name = 'vector'"
            )
        ).scalar()

        if has_vector:
            clean = re.sub(r"--\s*__PGVECTOR_\w+__[^\n]*", "", pgvector_sql)
            for raw in sqlparse.split(clean):
                stmt = raw.strip()
                if not stmt:
                    continue
                stripped = re.sub(r"--[^\n]*", "", stmt).strip()
                if not stripped:
                    continue
                conn.execute(sa.text(stmt))
        else:
            print(
                "\n[WARN] pgvector extension not available — skipping knowledge_chunks.\n"
                "       Use pgvector/pgvector:pg16 image and re-run migrations.\n"
            )


def downgrade() -> None:
    raise NotImplementedError(
        "Baseline downgrade would drop the entire schema — restore from backup."
    )
