"""Billing endpoints: usage, checkout, portal, history."""
from __future__ import annotations

import uuid
from decimal import Decimal

import structlog
from fastapi import APIRouter, HTTPException
from opentelemetry.trace import StatusCode, get_tracer
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from apps.api.billing.constants import overage_rate_for_plan
from apps.api.core.config import settings
from apps.api.core.database import get_session_with_tenant
from apps.api.core.deps import TenantAdmin
from apps.api.models.auth import Tenant
from apps.api.models.billing import BillingEvent

log = structlog.get_logger(__name__)
tracer = get_tracer(__name__)
router = APIRouter()


class UsageResponse(BaseModel):
    plan: str
    credits_included: int
    credits_used: int
    credits_remaining: int
    overage_credits: int
    estimated_overage_cost: float
    period_end: str | None
    stripe_status: str | None
    extra_balance_usd: float
    overage_rate_per_credit: float
    # Token-based billing fields
    used_real_cost_usd: float = 0.0
    included_budget_usd: float | None = None
    remaining_budget_usd: float | None = None
    budget_usage_pct: float = 0.0


class CheckoutRequest(BaseModel):
    plan: str


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


class TopUpRequest(BaseModel):
    amount_usd: float = Field(..., ge=5.0, le=500.0)


class TopUpResponse(BaseModel):
    checkout_url: str


@router.get("/usage", response_model=UsageResponse)
async def get_usage(current: TenantAdmin) -> UsageResponse:
    _user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
        tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    included = tenant.credits_monthly_limit
    used = tenant.credits_used_this_period
    remaining = max(0, tenant.credits_remaining)
    overage = max(0, used - included)
    rate = overage_rate_for_plan(tenant.plan)
    estimated_overage_cost = round(overage * rate, 2)
    extra_bal = float(tenant.extra_balance_usd or 0)

    from apps.api.billing.billing_gate import PLAN_INCLUDED_REAL_COST
    real_cost_used = float(getattr(tenant, "real_cost_used_this_period", 0) or 0)
    included_budget = PLAN_INCLUDED_REAL_COST.get(tenant.plan)
    remaining_budget = max(0, float(included_budget or 0) - real_cost_used) if included_budget is not None else None
    budget_pct = round(real_cost_used / float(included_budget) * 100, 1) if included_budget and included_budget > 0 else 0.0

    return UsageResponse(
        plan=tenant.plan,
        credits_included=included,
        credits_used=used,
        credits_remaining=remaining,
        overage_credits=overage,
        estimated_overage_cost=estimated_overage_cost,
        period_end=tenant.stripe_current_period_end.isoformat() if tenant.stripe_current_period_end else None,
        stripe_status=tenant.stripe_subscription_status,
        extra_balance_usd=extra_bal,
        overage_rate_per_credit=rate,
        used_real_cost_usd=round(real_cost_used, 6),
        included_budget_usd=float(included_budget) if included_budget is not None else None,
        remaining_budget_usd=remaining_budget,
        budget_usage_pct=budget_pct,
    )


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout_session(body: CheckoutRequest, current: TenantAdmin) -> CheckoutResponse:
    _user, tenant_id, _ = current

    valid_plans = ("starter", "growth", "scale")
    if body.plan not in valid_plans:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Choose from: {valid_plans}")

    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
        tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    from apps.api.billing.stripe_service import StripeService
    stripe_service = StripeService()

    base = settings.frontend_url.rstrip("/")
    checkout_url = await stripe_service.create_checkout_session(
        tenant=tenant,
        plan=body.plan,
        success_url=f"{base}/billing?upgrade=success",
        cancel_url=f"{base}/billing",
    )
    return CheckoutResponse(checkout_url=checkout_url)


@router.post("/top-up", response_model=TopUpResponse)
async def create_top_up_session(body: TopUpRequest, current: TenantAdmin) -> TopUpResponse:
    _user, tenant_id, _ = current

    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
        tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    from apps.api.billing.stripe_service import StripeService
    stripe_service = StripeService()
    base = settings.frontend_url.rstrip("/")
    with tracer.start_as_current_span("create_top_up_session") as span:
        try:
            checkout_url = await stripe_service.create_top_up_session(
                tenant=tenant,
                amount_usd=Decimal(str(body.amount_usd)),
                success_url=f"{base}/billing?topup=success",
                cancel_url=f"{base}/billing?topup=cancelled",
            )
        except ValueError as e:
            span.record_exception(e)
            span.set_status(StatusCode.ERROR, str(e))
            log.error("top_up_session_creation_failed", tenant_id=tenant_id, amount=body.amount_usd, exc_info=True)
            raise HTTPException(status_code=400, detail=str(e)) from e
    return TopUpResponse(checkout_url=checkout_url)


@router.get("/portal", response_model=PortalResponse)
async def create_portal_session(current: TenantAdmin) -> PortalResponse:
    _user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
        tenant = result.scalar_one_or_none()

    if not tenant or not tenant.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No active subscription found.")

    from apps.api.billing.stripe_service import StripeService
    stripe_service = StripeService()
    base = settings.frontend_url.rstrip("/")
    portal_url = await stripe_service.create_customer_portal_session(
        tenant=tenant,
        return_url=f"{base}/billing",
    )
    return PortalResponse(portal_url=portal_url)


@router.get("/history")
async def billing_history(current: TenantAdmin, limit: int = 20, offset: int = 0) -> list[dict]:
    _user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(BillingEvent)
            .where(BillingEvent.tenant_id == uuid.UUID(tenant_id))
            .order_by(desc(BillingEvent.created_at))
            .limit(limit)
            .offset(offset)
        )
        events = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "credits_delta": e.credits_delta,
            "usd_amount": float(e.usd_amount),
            "description": e.description,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]
