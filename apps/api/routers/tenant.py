"""Tenant settings and onboarding endpoints."""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from apps.api.core.database import get_session_with_tenant
from apps.api.core.deps import CurrentUser, TenantAdmin
from apps.api.models.auth import Tenant

log = structlog.get_logger(__name__)
router = APIRouter()


@router.get("")
async def get_tenant(current: CurrentUser) -> dict:
    user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
        tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "plan": tenant.plan,
        "credits_remaining": tenant.credits_remaining,
        "credits_monthly_limit": tenant.credits_monthly_limit,
        "onboarding_step": tenant.onboarding_step,
        "needs_profile_completion": tenant.needs_profile_completion,
        "stripe_status": tenant.stripe_subscription_status,
        "billing_email": tenant.billing_email,
        "created_at": tenant.created_at.isoformat(),
    }


class UpdateTenantProfileRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_ok(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be empty.")
        return v.strip()


@router.patch("/profile")
async def update_tenant_profile(body: UpdateTenantProfileRequest, current: TenantAdmin) -> dict:
    """Workspace display name (admin only). Clears the profile-completion banner."""
    _user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404)
        tenant.name = body.name
        tenant.needs_profile_completion = False
    return {"name": body.name, "needs_profile_completion": False}


class UpdateOnboardingRequest(BaseModel):
    step: int


@router.patch("/onboarding")
async def update_onboarding(body: UpdateOnboardingRequest, current: CurrentUser) -> dict:
    user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404)
        tenant.onboarding_step = max(tenant.onboarding_step, body.step)
    return {"onboarding_step": tenant.onboarding_step}
