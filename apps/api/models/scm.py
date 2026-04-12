"""SCM connection and repository models."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.base import Base


class ScmConnection(Base):
    __tablename__ = "scm_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    scm_type: Mapped[str] = mapped_column(
        Enum("github", "gitlab", "bitbucket", "azure_devops", name="scm_type_enum"), nullable=False
    )
    encrypted_token: Mapped[bytes | None] = mapped_column()
    token_scope: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    installation_id: Mapped[str | None] = mapped_column(Text)
    org_login: Mapped[str | None] = mapped_column(Text)
    org_avatar_url: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    scm_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scm_connections.id", ondelete="SET NULL")
    )
    scm_repo_id: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    default_branch: Mapped[str] = mapped_column(Text, nullable=False, default="main")
    clone_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    webhook_id: Mapped[str | None] = mapped_column(Text)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schedule_cron: Mapped[str] = mapped_column(Text, nullable=False, default="0 8 * * 1")
    schedule_ref: Mapped[str] = mapped_column(Text, nullable=False, default="main")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    repo_type: Mapped[str | None] = mapped_column(
        Enum("app", "iac", "library", "monorepo", name="repo_type_enum"), nullable=True
    )
    language: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    observability_backend: Mapped[str | None] = mapped_column(
        Enum("datadog", "grafana", "prometheus", "dynatrace", "splunk", name="obs_backend_enum"), nullable=True
    )
    # Sub-type for app repos: "web_service" | "api" | "worker" | "websocket" | "cli" | "other"
    app_subtype: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cloud provider for IaC repos: "aws" | "azure" | "gcp" | "multi" | "other"
    iac_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Telemetry instrumentation library in use: "otel" | "datadog" | "mixed" | "none" | "other"
    instrumentation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Metadata hints for observability backend (e.g. Datadog tags, Prometheus labels)
    obs_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_map: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Tracks when context_summary was last refreshed; used to auto-enqueue context refresh jobs
    context_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    connection: Mapped[ScmConnection | None] = relationship()
    analysis_jobs: Mapped[list] = relationship("AnalysisJob", back_populates="repository")
