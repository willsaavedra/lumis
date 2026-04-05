"""Create knowledge_chunks table with pgvector HNSW index and RLS policy.

Revision ID: h8c9d0e1f2g3
Revises: g7b8c9d0e1f2
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'h8c9d0e1f2g3'
down_revision = 'g7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Check if pgvector extension is available before attempting to create it.
    # If not available (e.g. plain postgres:16 image), skip this migration gracefully.
    # Switch to pgvector/pgvector:pg16 in docker-compose.yml to enable this.
    result = conn.execute(sa.text(
        "SELECT COUNT(*) FROM pg_available_extensions WHERE name = 'vector'"
    ))
    vector_available = result.scalar() > 0

    if not vector_available:
        print(
            "\n[WARN] pgvector extension not available — skipping knowledge_chunks table.\n"
            "       Switch Postgres image to pgvector/pgvector:pg16 and re-run migrations.\n"
        )
        return

    # Enable pgvector extension
    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector;"))

    # Create the knowledge_chunks table
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        REFERENCES tenants(id) ON DELETE CASCADE,
            source_type TEXT        NOT NULL,
            content     TEXT        NOT NULL,
            embedding   vector(1536) NOT NULL,
            metadata    JSONB       DEFAULT '{}',
            language    TEXT,
            pillar      TEXT,
            repo_id     UUID        REFERENCES repositories(id) ON DELETE CASCADE,
            expires_at  TIMESTAMPTZ,
            created_at  TIMESTAMPTZ DEFAULT now()
        );
    """))

    # HNSW index — better performance than IVFFlat for this volume
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_idx
            ON knowledge_chunks
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
    """))

    # Composite index for frequent filter patterns
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_tenant_source_lang
            ON knowledge_chunks (tenant_id, source_type, language);
    """))

    # TTL index — for efficient cleanup of expired chunks
    conn.execute(sa.text("""
        CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_expires_at
            ON knowledge_chunks (expires_at)
            WHERE expires_at IS NOT NULL;
    """))

    # RLS: tenant sees their own chunks + global chunks (tenant_id IS NULL)
    conn.execute(sa.text("ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;"))

    conn.execute(sa.text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'knowledge_chunks' AND policyname = 'rag_isolation'
            ) THEN
                CREATE POLICY rag_isolation ON knowledge_chunks
                    USING (
                        tenant_id IS NULL
                        OR tenant_id = current_setting('app.tenant_id')::UUID
                    );
            END IF;
        END $$;
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS knowledge_chunks;"))
