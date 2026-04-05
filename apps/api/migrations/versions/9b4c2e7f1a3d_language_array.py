"""change repositories.language from text to text array

Revision ID: 9b4c2e7f1a3d
Revises: 7f3a1b9c2d4e
Create Date: 2026-04-02

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '9b4c2e7f1a3d'
down_revision = '7f3a1b9c2d4e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        ALTER TABLE repositories
        ALTER COLUMN language TYPE TEXT[]
        USING CASE WHEN language IS NULL THEN NULL ELSE ARRAY[language] END
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        ALTER TABLE repositories
        ALTER COLUMN language TYPE TEXT
        USING CASE WHEN language IS NULL THEN NULL ELSE language[1] END
    """))
