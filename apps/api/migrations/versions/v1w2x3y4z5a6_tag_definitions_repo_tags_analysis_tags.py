"""tag_definitions, repo_tags, analysis_tags.

Revision ID: v1w2x3y4z5a6
Revises: u7v8w9x0y1z2
Create Date: 2026-04-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision = "v1w2x3y4z5a6"
down_revision = "u7v8w9x0y1z2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tag_definitions ─────────────────────────────────────────────────
    op.create_table(
        "tag_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("allowed_values", ARRAY(sa.Text()), nullable=True),
        sa.Column("color_class", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "key", name="uq_tag_definitions_tenant_key"),
    )
    op.create_index("idx_tag_definitions_tenant", "tag_definitions", ["tenant_id"])
    op.execute("ALTER TABLE tag_definitions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tag_definitions "
        "USING (tenant_id = current_setting('app.tenant_id')::UUID)"
    )

    # ── repo_tags ───────────────────────────────────────────────────────
    op.create_table(
        "repo_tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repo_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "source", sa.Text(), nullable=False, server_default=sa.text("'user'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("repo_id", "key", name="uq_repo_tags_repo_key"),
        sa.CheckConstraint("source IN ('user','auto','inherited')", name="ck_repo_tags_source"),
    )
    op.create_index("idx_repo_tags_repo", "repo_tags", ["repo_id"])
    op.create_index("idx_repo_tags_tenant", "repo_tags", ["tenant_id"])
    op.create_index("idx_repo_tags_key_val", "repo_tags", ["tenant_id", "key", "value"])
    op.execute("ALTER TABLE repo_tags ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON repo_tags "
        "USING (tenant_id = current_setting('app.tenant_id')::UUID)"
    )

    # ── analysis_tags ───────────────────────────────────────────────────
    op.create_table(
        "analysis_tags",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'user'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("job_id", "key", name="uq_analysis_tags_job_key"),
    )
    op.create_index("idx_analysis_tags_job", "analysis_tags", ["job_id"])
    op.create_index("idx_analysis_tags_tenant", "analysis_tags", ["tenant_id"])
    op.create_index("idx_analysis_tags_kv", "analysis_tags", ["tenant_id", "key", "value"])
    op.execute("ALTER TABLE analysis_tags ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON analysis_tags "
        "USING (tenant_id = current_setting('app.tenant_id')::UUID)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON analysis_tags")
    op.drop_index("idx_analysis_tags_kv", table_name="analysis_tags")
    op.drop_index("idx_analysis_tags_tenant", table_name="analysis_tags")
    op.drop_index("idx_analysis_tags_job", table_name="analysis_tags")
    op.drop_table("analysis_tags")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON repo_tags")
    op.drop_index("idx_repo_tags_key_val", table_name="repo_tags")
    op.drop_index("idx_repo_tags_tenant", table_name="repo_tags")
    op.drop_index("idx_repo_tags_repo", table_name="repo_tags")
    op.drop_table("repo_tags")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tag_definitions")
    op.drop_index("idx_tag_definitions_tenant", table_name="tag_definitions")
    op.drop_table("tag_definitions")
