"""Remove domain/criticality tag definitions, set all required=false, add repository tag definition."""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(text("""
        UPDATE tag_definitions SET required = false WHERE required = true
    """))

    conn.execute(text("""
        DELETE FROM tag_definitions
        WHERE key IN ('domain', 'criticality')
          AND id NOT IN (
              SELECT DISTINCT td.id
              FROM tag_definitions td
              JOIN repo_tags rt ON rt.key = td.key AND rt.tenant_id = td.tenant_id
          )
    """))

    conn.execute(text("""
        UPDATE tag_definitions SET required = false WHERE key = 'criticality'
    """))

    conn.execute(text("""
        INSERT INTO tag_definitions (id, tenant_id, key, label, description, required, allowed_values, color_class, sort_order)
        SELECT gen_random_uuid(), t.id, 'repository', 'Repository', 'Repository full name (auto-filled on activation)', false, NULL, 'tag-team', 1
        FROM tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM tag_definitions td
            WHERE td.tenant_id = t.id AND td.key = 'repository'
        )
    """))

    conn.execute(text("""
        INSERT INTO repo_tags (id, tenant_id, repo_id, key, value, source)
        SELECT gen_random_uuid(), r.tenant_id, r.id, 'repository', r.full_name, 'auto'
        FROM repositories r
        WHERE r.is_active = true
          AND NOT EXISTS (
              SELECT 1 FROM repo_tags rt
              WHERE rt.repo_id = r.id AND rt.key = 'repository'
          )
    """))


def downgrade() -> None:
    pass
