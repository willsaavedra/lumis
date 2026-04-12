"""Remove domain/criticality tag definitions and set all required=false."""
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


def downgrade() -> None:
    pass
