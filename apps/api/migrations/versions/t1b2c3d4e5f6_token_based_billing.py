"""Token-based billing: scope_type, cost columns, cost_events table.

Revision ID: t1b2c3d4e5f6
Revises: 4e92a0be20c0
Create Date: 2026-04-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "t1b2c3d4e5f6"
down_revision = "o5p6q7r8s9t0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── analysis_jobs: add new cost columns ──────────────────────────────
    op.add_column("analysis_jobs", sa.Column("scope_type", sa.Text(), nullable=True))
    op.add_column("analysis_jobs", sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False))
    op.add_column("analysis_jobs", sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False))
    op.add_column("analysis_jobs", sa.Column("input_tokens_cached", sa.Integer(), server_default="0", nullable=False))
    op.add_column("analysis_jobs", sa.Column("llm_cost_usd", sa.Numeric(10, 6), server_default="0", nullable=False))
    op.add_column("analysis_jobs", sa.Column("infra_cost_usd", sa.Numeric(10, 6), server_default="0", nullable=False))
    op.add_column("analysis_jobs", sa.Column("total_cost_usd", sa.Numeric(10, 6), server_default="0", nullable=False))
    op.add_column("analysis_jobs", sa.Column("margin_applied", sa.Numeric(4, 2), server_default="3.0", nullable=False))
    op.add_column("analysis_jobs", sa.Column("estimated_cost_usd", sa.Numeric(10, 6), server_default="0", nullable=False))
    op.add_column("analysis_jobs", sa.Column("selected_paths", JSONB(), server_default="[]", nullable=False))

    # Migrate analysis_type values -> scope_type
    op.execute("""
        UPDATE analysis_jobs SET scope_type = CASE
            WHEN analysis_type = 'quick' THEN 'selection'
            WHEN analysis_type = 'full' THEN 'full_repo'
            WHEN analysis_type = 'repository' THEN 'full_repo'
            WHEN analysis_type = 'context' THEN 'context'
            ELSE 'full_repo'
        END
    """)
    op.alter_column("analysis_jobs", "scope_type", nullable=False, server_default="full_repo")

    # ── analysis_results: add cost_breakdown JSONB ───────────────────────
    op.add_column("analysis_results", sa.Column("cost_breakdown", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=True))

    # ── tenants: add real_cost_used_this_period ──────────────────────────
    op.add_column("tenants", sa.Column("real_cost_used_this_period", sa.Numeric(12, 6), server_default="0", nullable=False))

    # ── cost_events table ────────────────────────────────────────────────
    op.create_table(
        "cost_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0"),
        sa.Column("output_tokens", sa.Integer(), server_default="0"),
        sa.Column("cached_tokens", sa.Integer(), server_default="0"),
        sa.Column("llm_provider", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), server_default="0"),
        sa.Column("cumulative_cost", sa.Numeric(10, 6), server_default="0"),
        sa.Column("metadata_json", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_cost_events_job_id", "cost_events", ["job_id"])
    op.create_index("ix_cost_events_tenant_id", "cost_events", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_cost_events_tenant_id", table_name="cost_events")
    op.drop_index("ix_cost_events_job_id", table_name="cost_events")
    op.drop_table("cost_events")
    op.drop_column("tenants", "real_cost_used_this_period")
    op.drop_column("analysis_results", "cost_breakdown")
    op.drop_column("analysis_jobs", "selected_paths")
    op.drop_column("analysis_jobs", "estimated_cost_usd")
    op.drop_column("analysis_jobs", "margin_applied")
    op.drop_column("analysis_jobs", "total_cost_usd")
    op.drop_column("analysis_jobs", "infra_cost_usd")
    op.drop_column("analysis_jobs", "llm_cost_usd")
    op.drop_column("analysis_jobs", "input_tokens_cached")
    op.drop_column("analysis_jobs", "output_tokens")
    op.drop_column("analysis_jobs", "input_tokens")
    op.drop_column("analysis_jobs", "scope_type")
