"""TS Agent compat: findings columns, enum→TEXT, new pillars, indexes.

Covers the remaining DDL from infra/migrations/005_ts_agent_compat.sql that
was not yet tracked by Alembic (agent_breakdown, crossrun_summary,
previous_job_id, and analysis_type 'context' were handled in earlier revisions).

Revision ID: o6p7q8r9s0t1
Revises: n5o6p7q8r9s0
"""
from alembic import op
import sqlalchemy as sa

revision = "o6p7q8r9s0t1"
down_revision = "n5o6p7q8r9s0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. dimension enum → TEXT
    conn.execute(sa.text("ALTER TABLE findings ALTER COLUMN dimension TYPE TEXT;"))
    conn.execute(sa.text("DROP TYPE IF EXISTS dimension_enum;"))

    # 2. New pillar enum values
    for value in ("security", "efficiency", "compliance"):
        conn.execute(sa.text(f"""
            DO $$ BEGIN
              ALTER TYPE pillar_enum ADD VALUE IF NOT EXISTS '{value}';
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """))

    # 3. pillar and severity enum → TEXT
    conn.execute(sa.text("ALTER TABLE findings ALTER COLUMN pillar TYPE TEXT;"))
    conn.execute(sa.text("ALTER TABLE findings ALTER COLUMN severity TYPE TEXT;"))
    conn.execute(sa.text("DROP TYPE IF EXISTS pillar_enum;"))
    conn.execute(sa.text("DROP TYPE IF EXISTS severity_enum;"))

    # 4. New columns on findings
    conn.execute(sa.text("""
        ALTER TABLE findings
          ADD COLUMN IF NOT EXISTS source_agent TEXT,
          ADD COLUMN IF NOT EXISTS prompt_mode TEXT,
          ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT false,
          ADD COLUMN IF NOT EXISTS confidence REAL,
          ADD COLUMN IF NOT EXISTS reasoning_excerpt TEXT;
    """))

    # 5. Indexes
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_findings_source_agent ON findings(source_agent);"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_findings_confidence ON findings(confidence);"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_findings_verified ON findings(verified);"
    ))


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("DROP INDEX IF EXISTS idx_findings_verified;"))
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_findings_confidence;"))
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_findings_source_agent;"))

    conn.execute(sa.text("""
        ALTER TABLE findings
          DROP COLUMN IF EXISTS source_agent,
          DROP COLUMN IF EXISTS prompt_mode,
          DROP COLUMN IF EXISTS verified,
          DROP COLUMN IF EXISTS confidence,
          DROP COLUMN IF EXISTS reasoning_excerpt;
    """))

    # Recreate enums (best-effort; values may differ from original)
    conn.execute(sa.text("""
        DO $$ BEGIN
          CREATE TYPE pillar_enum AS ENUM ('metrics','logs','traces','iac','pipeline');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))
    conn.execute(sa.text(
        "ALTER TABLE findings ALTER COLUMN pillar TYPE pillar_enum USING pillar::pillar_enum;"
    ))

    conn.execute(sa.text("""
        DO $$ BEGIN
          CREATE TYPE severity_enum AS ENUM ('critical','warning','info');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))
    conn.execute(sa.text(
        "ALTER TABLE findings ALTER COLUMN severity TYPE severity_enum USING severity::severity_enum;"
    ))

    conn.execute(sa.text("""
        DO $$ BEGIN
          CREATE TYPE dimension_enum AS ENUM ('cost','snr','pipeline','compliance','coverage');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))
    conn.execute(sa.text(
        "ALTER TABLE findings ALTER COLUMN dimension TYPE dimension_enum USING dimension::dimension_enum;"
    ))
