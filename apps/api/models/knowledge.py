"""Knowledge base model for RAG (Retrieval-Augmented Generation)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.base import Base

# source_type values
SOURCE_TYPES = (
    "otel_docs",
    "dd_docs",
    "tenant_standards",
    "analysis_history",
    "cross_repo_pattern",
)

# pillar values
KNOWLEDGE_PILLARS = ("metrics", "logs", "traces", "iac")

# language values
KNOWLEDGE_LANGUAGES = ("go", "python", "java", "node", "terraform", "helm")


class KnowledgeChunk(Base):
    """
    A chunk of text in the knowledge base, paired with its vector embedding.

    tenant_id = NULL  → global chunk (shared across all tenants)
    tenant_id = <id>  → tenant-private chunk (isolated via RLS)

    Used by retrieve_context_node to inject relevant context into analyze_coverage prompts.
    """
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # NULL = global (visible to all tenants); SET = isolated per tenant via RLS
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )

    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    # otel_docs | dd_docs | tenant_standards | analysis_history | cross_repo_pattern

    content: Mapped[str] = mapped_column(Text, nullable=False)
    # The text injected into the LLM system prompt

    # embedding stored as raw JSONB array; pgvector type handled in raw SQL
    # The actual column is vector(1536) in Postgres — SQLAlchemy can't natively map this
    # without pgvector extension, so we store the embedding as a separate concern in migration.
    # For reads/writes we use raw SQL via session.execute(text(...))

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default={})
    # source_url, language, pillar, repo_id, file_path, doc_version, tags

    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    # go | python | java | node | terraform | helm — used for retrieval filtering

    pillar: Mapped[str | None] = mapped_column(Text, nullable=True)
    # metrics | logs | traces | iac — used for retrieval filtering

    repo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True
    )
    # For analysis_history chunks: which repo generated this chunk

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # TTL: docs expire in 30 days, history in 90 days. NULL = no expiration

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
