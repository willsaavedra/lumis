"""Nullable password_hash + oauth_google_sub for Google sign-in.

Revision ID: j0e1f2g3h4i5
Revises: h8c9d0e1f2g3
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'j0e1f2g3h4i5'
down_revision = 'h8c9d0e1f2g3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('users', 'password_hash', existing_type=sa.Text(), nullable=True)
    op.add_column('users', sa.Column('oauth_google_sub', sa.Text(), nullable=True))
    op.create_index('ix_users_oauth_google_sub', 'users', ['oauth_google_sub'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_users_oauth_google_sub', table_name='users')
    op.drop_column('users', 'oauth_google_sub')
    op.alter_column('users', 'password_hash', existing_type=sa.Text(), nullable=False)
