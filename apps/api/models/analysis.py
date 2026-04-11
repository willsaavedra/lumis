"""Analysis job, result, finding, and cost event models."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.base import Base

# Feedback signal values — must match the DB enum
FEEDBACK_SIGNALS = ("thumbs_up", "thumbs_down", "ignored", "applied")

# Feedback target: "finding" = was the finding accurate? "suggestion" = was the code fix helpful?
FEEDBACK_TARGETS = ("finding", "suggestion")


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    repo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "completed", "failed", name="job_status_enum"),
        nullable=False, default="pending",
    )
    trigger: Mapped[str] = mapped_column(
        Enum("pr", "push", "manual", "scheduled", name="trigger_enum"), nullable=False
    )
    pr_number: Mapped[int | None] = mapped_column(Integer)
    commit_sha: Mapped[str | None] = mapped_column(Text)
    branch_ref: Mapped[str | None] = mapped_column(Text)
    changed_files: Mapped[dict | None] = mapped_column(JSONB)
    analysis_type: Mapped[str] = mapped_column(
        Enum("quick", "full", "repository", "context", name="analysis_type_enum"),
        nullable=False, default="full",
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="full_repo")
    llm_provider: Mapped[str] = mapped_column(Text, nullable=False, default="anthropic")
    credits_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    billing_reservation: Mapped[dict | None] = mapped_column(JSONB)
    credits_consumed: Mapped[int | None] = mapped_column(Integer)
    # Token-based billing columns
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    input_tokens_cached: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    llm_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default="0", default=0)
    infra_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default="0", default=0)
    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default="0", default=0)
    margin_applied: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, server_default="3.0", default=Decimal("3.0"))
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default="0", default=0)
    selected_paths: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="[]")
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fix_pr_url: Mapped[str | None] = mapped_column(Text)
    fix_pr_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    repository: Mapped = relationship("Repository", back_populates="analysis_jobs")
    result: Mapped[AnalysisResult | None] = relationship(
        back_populates="job",
        uselist=False,
        foreign_keys="[AnalysisResult.job_id]",
    )


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), unique=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    score_global: Mapped[int | None] = mapped_column(Integer)
    score_metrics: Mapped[int | None] = mapped_column(Integer)
    score_logs: Mapped[int | None] = mapped_column(Integer)
    score_traces: Mapped[int | None] = mapped_column(Integer)
    score_cost: Mapped[int | None] = mapped_column(Integer)
    score_snr: Mapped[int | None] = mapped_column(Integer)
    score_pipeline: Mapped[int | None] = mapped_column(Integer)
    score_compliance: Mapped[int | None] = mapped_column(Integer)
    previous_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="SET NULL"), nullable=True)
    crossrun_summary: Mapped[dict | None] = mapped_column(JSONB)
    findings: Mapped[dict | None] = mapped_column(JSONB)
    call_graph_path: Mapped[str | None] = mapped_column(Text)
    raw_llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    cost_breakdown: Mapped[dict | None] = mapped_column(JSONB, server_default=sa.text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job: Mapped[AnalysisJob] = relationship(
        back_populates="result",
        foreign_keys="[AnalysisResult.job_id]",
    )
    findings_list: Mapped[list[Finding]] = relationship(back_populates="result")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_results.id", ondelete="CASCADE"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    pillar: Mapped[str] = mapped_column(
        Enum("metrics", "logs", "traces", "iac", "pipeline", "compliance", "cost", "snr", name="pillar_enum", create_type=False), nullable=False
    )
    severity: Mapped[str] = mapped_column(
        Enum("critical", "warning", "info", name="severity_enum"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(
        Enum("cost", "snr", "pipeline", "compliance", "coverage", name="dimension_enum"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    suggestion: Mapped[str | None] = mapped_column(Text)
    estimated_monthly_cost_impact: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    result: Mapped[AnalysisResult] = relationship(back_populates="findings_list")
    feedback: Mapped[list[FindingFeedback]] = relationship(back_populates="finding")


class FindingFeedback(Base):
    """
    User feedback signal for individual findings and their suggestions.

    target_type distinguishes:
      finding    → Was the finding accurate / is it a real issue?
                   thumbs_up = TP, thumbs_down = FP, ignored = acknowledged but skipped
      suggestion → Was the suggested code fix helpful?
                   thumbs_up = helpful, thumbs_down = wrong/unhelpful, applied = fix was applied

    Powers the tuning flywheel:
      thumbs_down (finding)    → false positive dataset for eval
      applied     (suggestion) → confirmed true positive + useful suggestion for few-shot
    """
    __tablename__ = "finding_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    finding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    target_type: Mapped[str] = mapped_column(
        Enum(*FEEDBACK_TARGETS, name="feedback_target_enum"),
        nullable=False,
        server_default="finding",
    )
    signal: Mapped[str] = mapped_column(
        Enum(*FEEDBACK_SIGNALS, name="feedback_signal_enum"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
    feedback_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    finding: Mapped[Finding] = relationship(back_populates="feedback")


class CostEvent(Base):
    """Per-node and final cost events for token-based billing."""
    __tablename__ = "cost_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cached_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    llm_provider: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), server_default="0")
    cumulative_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), server_default="0")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
