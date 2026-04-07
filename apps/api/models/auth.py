"""Authentication and tenant models."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.models.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(
        Enum("free", "starter", "growth", "scale", "enterprise", name="plan_enum"),
        nullable=False,
        default="free",
    )
    credits_remaining: Mapped[int] = mapped_column(nullable=False, default=50)
    credits_monthly_limit: Mapped[int] = mapped_column(nullable=False, default=50)
    credits_used_this_period: Mapped[int] = mapped_column(nullable=False, default=0)
    extra_balance_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    real_cost_used_this_period: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default="0", default=0)
    onboarding_step: Mapped[int] = mapped_column(nullable=False, default=0)
    needs_profile_completion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Stripe
    stripe_customer_id: Mapped[str | None] = mapped_column(Text, unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(Text, unique=True)
    stripe_subscription_status: Mapped[str | None] = mapped_column(Text)
    stripe_current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stripe_base_price_id: Mapped[str | None] = mapped_column(Text)
    stripe_overage_price_id: Mapped[str | None] = mapped_column(Text)
    billing_email: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organizations: Mapped[list[Organization]] = relationship(back_populates="tenant")
    users: Mapped[list[User]] = relationship(back_populates="tenant")
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="tenant")
    memberships: Mapped[list["TenantMembership"]] = relationship(back_populates="tenant")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    scm_type: Mapped[str | None] = mapped_column(
        Enum("github", "gitlab", "bitbucket", "azure_devops", name="scm_type_enum")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(back_populates="organizations")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    email: Mapped[str] = mapped_column(Text, nullable=False)
    # Null when the user only signs in with Google (no password).
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Google OIDC "sub" — unique per Google account when set.
    oauth_google_sub: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    role: Mapped[str] = mapped_column(
        Enum("owner", "admin", "member", "viewer", name="user_role_enum"),
        nullable=False,
        default="member",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(back_populates="users")
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="user")
    tenant_memberships: Mapped[list["TenantMembership"]] = relationship(back_populates="user")


membership_role_enum = Enum("admin", "operator", "viewer", name="membership_role_enum")


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", name="uq_tenant_memberships_user_tenant"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(membership_role_enum, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="tenant_memberships", foreign_keys=[user_id])
    tenant: Mapped[Tenant] = relationship(back_populates="memberships")


class TenantInvite(Base):
    __tablename__ = "tenant_invites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(membership_role_enum, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship()


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    key_hint: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False, default="Default")
    scope: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=["*"])
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(back_populates="api_keys")
    user: Mapped[User | None] = relationship(back_populates="api_keys")
