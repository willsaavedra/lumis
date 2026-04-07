"""Stripe integration service."""
from __future__ import annotations

from decimal import Decimal

import structlog
import stripe
from stripe import StripeClient

from apps.api.core.config import settings

log = structlog.get_logger(__name__)

# Plan → price IDs mapping
PLAN_PRICES = {
    "starter": {
        "base": settings.stripe_price_starter_base,
        "overage": settings.stripe_price_starter_overage,
    },
    "growth": {
        "base": settings.stripe_price_growth_base,
        "overage": settings.stripe_price_growth_overage,
    },
    "scale": {
        "base": settings.stripe_price_scale_base,
        "overage": settings.stripe_price_scale_overage,
    },
}


class StripeService:
    def __init__(self) -> None:
        stripe.api_key = settings.stripe_secret_key

    async def create_customer(self, tenant_id: str, email: str, name: str) -> str:
        """Create Stripe customer and save ID to DB. Called on first upgrade."""
        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={"tenant_id": str(tenant_id)},
            idempotency_key=f"customer-{tenant_id}",
        )
        log.info("stripe_customer_created", customer_id=customer.id, tenant_id=tenant_id)
        return customer.id

    async def create_checkout_session(
        self,
        tenant: object,
        plan: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """Create Stripe Checkout session for plan upgrade. Returns session URL."""
        prices = PLAN_PRICES.get(plan)
        if not prices:
            raise ValueError(f"Unknown plan: {plan}")

        # Create customer if not exists
        customer_id = getattr(tenant, "stripe_customer_id", None)
        if not customer_id:
            customer_id = await self.create_customer(
                tenant_id=str(tenant.id),
                email=getattr(tenant, "billing_email", "") or "",
                name=tenant.name,
            )
            # Save customer_id to DB
            from apps.api.core.database import get_session_with_tenant
            async with get_session_with_tenant(str(tenant.id)) as session:
                from apps.api.models.auth import Tenant
                from sqlalchemy import select
                result = await session.execute(select(Tenant).where(Tenant.id == tenant.id))
                db_tenant = result.scalar_one()
                db_tenant.stripe_customer_id = customer_id

        line_items = [{"price": prices["base"], "quantity": 1}]
        if prices["overage"]:
            line_items.append({"price": prices["overage"]})

        meta = {"tenant_id": str(tenant.id), "plan": plan}

        # If the tenant already has an active subscription, update its metadata
        # so the webhook handler can always find tenant_id from subscription.
        existing_sub_id = getattr(tenant, "stripe_subscription_id", None)
        if existing_sub_id:
            try:
                stripe.Subscription.modify(existing_sub_id, metadata=meta)
            except Exception as e:
                log.warning("stripe_subscription_metadata_update_failed",
                            subscription_id=existing_sub_id, error=str(e))

        # v3 key: ensures a fresh session is created with metadata on both
        # session and subscription_data (v2 may have been cached without metadata).
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=line_items,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=meta,
            subscription_data={"metadata": meta},
            idempotency_key=f"checkout-v3-{tenant.id}-{plan}",
        )
        return session.url

    async def create_top_up_session(
        self,
        tenant: object,
        amount_usd: Decimal,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """One-time Checkout to add prepaid USD wallet balance."""
        lo = Decimal("5.00")
        hi = Decimal("500.00")
        amt = Decimal(str(amount_usd)).quantize(Decimal("0.01"))
        if amt < lo or amt > hi:
            raise ValueError("Amount must be between $5.00 and $500.00")

        customer_id = getattr(tenant, "stripe_customer_id", None)
        if not customer_id:
            customer_id = await self.create_customer(
                tenant_id=str(tenant.id),
                email=getattr(tenant, "billing_email", "") or "",
                name=tenant.name,
            )
            from apps.api.core.database import get_session_with_tenant
            async with get_session_with_tenant(str(tenant.id)) as session:
                from apps.api.models.auth import Tenant
                from sqlalchemy import select
                result = await session.execute(select(Tenant).where(Tenant.id == tenant.id))
                db_tenant = result.scalar_one()
                db_tenant.stripe_customer_id = customer_id

        cents = int((amt * 100).quantize(Decimal("1")))
        meta = {"tenant_id": str(tenant.id), "type": "top_up"}
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": "Lumis extra usage balance"},
                        "unit_amount": cents,
                    },
                    "quantity": 1,
                }
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=meta,
        )
        return session.url

    async def create_customer_portal_session(self, tenant: object, return_url: str) -> str:
        """Create Stripe Customer Portal session."""
        session = stripe.billing_portal.Session.create(
            customer=tenant.stripe_customer_id,
            return_url=return_url,
        )
        return session.url

    async def report_usage(
        self,
        tenant_id: str,
        customer_id: str,
        credits_consumed: int,
        plan_limit: int,
        job_id: str,
        timestamp: object,
        *,
        credits_paid_from_wallet: int = 0,
    ) -> None:
        """Report overage credits to Stripe Meters. Skips units already covered by prepaid wallet."""
        if not settings.stripe_meter_id:
            return

        overage = max(0, credits_consumed - plan_limit)
        wallet_cover = max(0, min(overage, int(credits_paid_from_wallet or 0)))
        metered = max(0, overage - wallet_cover)
        log.info(
            "stripe_usage_report",
            tenant_id=tenant_id,
            included=plan_limit,
            consumed=credits_consumed,
            overage=overage,
            credits_paid_from_wallet=wallet_cover,
            metered=metered,
            job_id=job_id,
        )

        if metered <= 0:
            return

        import time
        stripe.billing.MeterEvent.create(
            event_name="analysis_credit_consumed",
            payload={
                "value": str(metered),
                "stripe_customer_id": customer_id,
            },
            identifier=str(job_id),
            timestamp=int(timestamp.timestamp()) if hasattr(timestamp, "timestamp") else int(time.time()),
        )

    async def report_cost_usage(
        self,
        tenant_id: str,
        customer_id: str,
        cost_usd_cents: int,
        job_id: str,
    ) -> None:
        """Report overage cost in cents to Stripe Meters (token-based billing)."""
        if not settings.stripe_meter_id:
            return
        if cost_usd_cents <= 0:
            return

        import time
        log.info(
            "stripe_cost_usage_report",
            tenant_id=tenant_id,
            cost_usd_cents=cost_usd_cents,
            job_id=job_id,
        )
        stripe.billing.MeterEvent.create(
            event_name="analysis_cost_consumed",
            payload={
                "value": str(cost_usd_cents),
                "stripe_customer_id": customer_id,
            },
            identifier=str(job_id),
            timestamp=int(time.time()),
        )

    async def cancel_subscription(self, tenant_id: str, subscription_id: str) -> None:
        """Cancel subscription at period end."""
        stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True,
        )
        log.info("stripe_subscription_canceling", tenant_id=tenant_id, subscription_id=subscription_id)
