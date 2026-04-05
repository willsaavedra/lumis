"""Observability vendor connection model."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.base import Base


class VendorConnection(Base):
    __tablename__ = "vendor_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    vendor: Mapped[str] = mapped_column(
        Enum("datadog", "grafana", "prometheus", "dynatrace", "splunk", name="vendor_enum"),
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(Text)
    api_key: Mapped[str | None] = mapped_column(Text)
    api_url: Mapped[str | None] = mapped_column(Text)   # required for grafana/prometheus/self-hosted
    extra_config: Mapped[dict | None] = mapped_column(JSONB)  # e.g. {"site": "datadoghq.eu"}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
