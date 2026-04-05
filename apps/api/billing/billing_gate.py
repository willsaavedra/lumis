"""BillingGate: credit reservation and consumption logic."""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import structlog
from fastapi import HTTPException, status

from apps.api.billing.constants import overage_rate_for_plan
from apps.api.core.config import settings
from apps.api.core.redis_client import get_redis, tenant_key

log = structlog.get_logger(__name__)

ANALYSIS_COSTS = {"quick": 1, "full": 3, "repository": 15, "context": 0}
RESERVATION_TTL = 600  # 10 minutes


def _quantize_usd(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _compute_reservation_split(
    *,
    cost: int,
    credits_remaining: int,
    extra_balance_usd: Decimal,
    plan: str,
) -> tuple[int, Decimal, int]:
    """
    Returns (plan_credits_used, usd_charged, credits_paid_from_wallet).
    credits_paid_from_wallet = cost - plan_credits_used (integer credits covered by USD wallet).
    """
    plan_credits_used = min(max(0, credits_remaining), cost)
    credits_from_wallet = cost - plan_credits_used
    rate = Decimal(str(overage_rate_for_plan(plan)))
    usd_charged = _quantize_usd(rate * Decimal(credits_from_wallet))
    return plan_credits_used, usd_charged, credits_from_wallet


class InsufficientCreditsError(Exception):
    pass


class BillingGate:
    async def check_and_reserve(
        self,
        tenant_id: str,
        analysis_type: str,
    ) -> tuple[str, dict]:
        """
        Reserve credits for an analysis. Returns (reservation_token, snapshot dict for persistence on AnalysisJob).
        Raises HTTP 402 if plan credits + USD wallet cannot cover cost.
        """
        from apps.api.core.database import get_session_with_tenant
        from apps.api.models.auth import Tenant
        from sqlalchemy import select

        cost = ANALYSIS_COSTS.get(analysis_type, 3)

        async with get_session_with_tenant(tenant_id) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
            tenant = result.scalar_one_or_none()

        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        # Check subscription status for paid plans
        if tenant.plan != "free" and tenant.stripe_subscription_status not in (
            "active", "trialing", "past_due", None
        ):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Subscription inactive. Please update your payment method.",
            )

        extra_bal = Decimal(str(tenant.extra_balance_usd or 0))
        plan_credits_used, usd_charged, credits_from_wallet = _compute_reservation_split(
            cost=cost,
            credits_remaining=tenant.credits_remaining,
            extra_balance_usd=extra_bal,
            plan=tenant.plan,
        )

        if extra_bal < usd_charged:
            need_usd = float(usd_charged)
            have_usd = float(extra_bal)
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Insufficient credits. This analysis costs {cost} credits "
                    f"({plan_credits_used} from your plan balance, "
                    f"{credits_from_wallet} from extra balance at ${float(overage_rate_for_plan(tenant.plan)):.2f}/credit "
                    f"= ${need_usd:.2f}). You have ${have_usd:.2f} in extra balance. "
                    "Add balance on the Billing page or upgrade your plan."
                ),
            )

        token = secrets.token_urlsafe(16)
        snapshot = {
            "cost": cost,
            "plan_credits_used": plan_credits_used,
            "usd_charged": str(usd_charged),
            "credits_paid_from_wallet": credits_from_wallet,
            "plan": tenant.plan,
            "analysis_type": analysis_type,
        }
        reservation = {
            "tenant_id": tenant_id,
            "analysis_type": analysis_type,
            "cost": cost,
            "credits_at_reservation": tenant.credits_remaining,
            "plan": tenant.plan,
            "is_overage": credits_from_wallet > 0,
            "plan_credits_used": plan_credits_used,
            "usd_charged": str(usd_charged),
            "credits_paid_from_wallet": credits_from_wallet,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        redis = get_redis()
        await redis.setex(
            tenant_key(tenant_id, f"reservation:{token}"),
            RESERVATION_TTL,
            json.dumps(reservation),
        )

        async with get_session_with_tenant(tenant_id) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
            t = result.scalar_one()
            t.credits_remaining = t.credits_remaining - plan_credits_used
            t.extra_balance_usd = _quantize_usd(Decimal(str(t.extra_balance_usd or 0)) - usd_charged)

        log.info(
            "credits_reserved",
            tenant_id=tenant_id,
            cost=cost,
            plan_credits_used=plan_credits_used,
            usd_charged=str(usd_charged),
            analysis_type=analysis_type,
            token=token[:8],
        )
        return token, snapshot

    async def consume(
        self,
        reservation_token: str,
        actual_credits: int,
        job_id: str,
        tenant_id: str,
        *,
        credits_paid_from_wallet: int = 0,
    ) -> None:
        """Mark reserved credits as consumed after successful analysis."""
        if reservation_token == "context_free":
            return

        redis = get_redis()
        raw = await redis.get(tenant_key(tenant_id, f"reservation:{reservation_token}"))
        if not raw:
            log.warning("reservation_expired_recording_consumption", token=reservation_token[:8])
            reservation = {
                "plan": "unknown",
                "analysis_type": "full",
                "cost": actual_credits,
                "credits_paid_from_wallet": credits_paid_from_wallet,
            }
        else:
            reservation = json.loads(raw)
            credits_paid_from_wallet = int(reservation.get("credits_paid_from_wallet") or credits_paid_from_wallet)

        from apps.api.core.database import get_session_with_tenant
        from apps.api.models.auth import Tenant
        from apps.api.models.billing import BillingEvent
        from sqlalchemy import select

        stripe_customer_id: str | None = None
        plan_for_stripe = reservation.get("plan") or "unknown"

        async with get_session_with_tenant(tenant_id) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
            tenant = result.scalar_one()

            tenant.credits_used_this_period += actual_credits
            stripe_customer_id = tenant.stripe_customer_id
            plan_for_stripe = reservation.get("plan") or tenant.plan

            event = BillingEvent(
                tenant_id=uuid.UUID(tenant_id),
                job_id=uuid.UUID(job_id),
                event_type="consumed",
                credits_delta=-actual_credits,
                description=f"Analysis {job_id[:8]} completed ({reservation.get('analysis_type', 'unknown')})",
            )
            session.add(event)

        plan = plan_for_stripe
        if plan != "free" and stripe_customer_id:
            from apps.api.billing.stripe_service import StripeService
            stripe_svc = StripeService()
            await stripe_svc.report_usage(
                tenant_id=tenant_id,
                customer_id=stripe_customer_id,
                credits_consumed=actual_credits,
                plan_limit=settings.plan_credits.get(plan, 50),
                job_id=job_id,
                timestamp=datetime.now(timezone.utc),
                credits_paid_from_wallet=credits_paid_from_wallet,
            )

        await redis.delete(tenant_key(tenant_id, f"reservation:{reservation_token}"))

    async def release(
        self,
        reservation_token: str,
        tenant_id: str,
        cost: int,
        billing_snapshot: dict | None = None,
    ) -> None:
        """Refund reserved credits and USD on analysis failure."""
        if cost == 0 or reservation_token == "context_free":
            return

        redis = get_redis()
        raw = await redis.get(tenant_key(tenant_id, f"reservation:{reservation_token}"))
        if raw:
            reservation = json.loads(raw)
            plan_credits_used = int(reservation.get("plan_credits_used", cost))
            usd_charged = Decimal(str(reservation.get("usd_charged") or "0"))
        elif billing_snapshot:
            plan_credits_used = int(billing_snapshot.get("plan_credits_used", cost))
            usd_charged = Decimal(str(billing_snapshot.get("usd_charged") or "0"))
        else:
            plan_credits_used = cost
            usd_charged = Decimal("0")

        from apps.api.core.database import get_session_with_tenant
        from apps.api.models.auth import Tenant
        from apps.api.models.billing import BillingEvent
        from sqlalchemy import select

        async with get_session_with_tenant(tenant_id) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
            tenant = result.scalar_one()
            tenant.credits_remaining = min(
                tenant.credits_monthly_limit,
                tenant.credits_remaining + plan_credits_used,
            )
            tenant.extra_balance_usd = _quantize_usd(
                Decimal(str(tenant.extra_balance_usd or 0)) + usd_charged
            )

            event = BillingEvent(
                tenant_id=uuid.UUID(tenant_id),
                event_type="released",
                credits_delta=plan_credits_used,
                usd_amount=usd_charged,
                description="Credits refunded for failed analysis",
            )
            session.add(event)

        await redis.delete(tenant_key(tenant_id, f"reservation:{reservation_token}"))
        log.info(
            "credits_released",
            tenant_id=tenant_id,
            plan_credits_used=plan_credits_used,
            usd_refunded=str(usd_charged),
        )
