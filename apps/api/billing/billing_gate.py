"""BillingGate: token-based billing with per-plan margins and budget tracking."""
from __future__ import annotations

import json
import os
import secrets
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import structlog
from fastapi import HTTPException, status

from apps.api.billing.constants import overage_rate_for_plan
from apps.api.core.config import settings
from apps.api.core.redis_client import get_redis, tenant_key

log = structlog.get_logger(__name__)

USE_TOKEN_BILLING = os.getenv("USE_TOKEN_BILLING", "true").lower() == "true"

# ── Legacy credit-based costs (rollback / backwards compat) ──────────────
LEGACY_ANALYSIS_COSTS = {"quick": 1, "full": 3, "repository": 15, "context": 0}
# Keep importable alias for any callers that still reference the old name
ANALYSIS_COSTS = LEGACY_ANALYSIS_COSTS

RESERVATION_TTL = 600  # 10 minutes

# ── LLM rate constants (USD per million tokens) ─────────────────────────
LLM_RATES: dict[str, dict[str, float]] = {
    "anthropic": {"input": 3.00, "output": 15.00, "cache": 0.30},
    "cerebra_ai": {"input": 0.40, "output": 1.60, "cache": 0.04},
}

INFRA_COST_PER_FILE = 0.0008
RAG_COST_PER_CHUNK = 0.00002

PLAN_MARGINS: dict[str, float] = {
    "free": 5.0,
    "starter": 4.0,
    "growth": 3.0,
    "scale": 2.5,
    "enterprise": 2.0,
}

PLAN_INCLUDED_REAL_COST: dict[str, float | None] = {
    "free": 0.50,
    "starter": 12.00,
    "growth": 50.00,
    "scale": 180.00,
    "enterprise": None,
}

DEFAULT_PROVIDER_PER_PLAN: dict[str, str] = {
    "free": "cerebra_ai",
    "starter": "cerebra_ai",
    "growth": "cerebra_ai",
    "scale": "anthropic",
    "enterprise": "anthropic",
}


# ── Dataclasses ──────────────────────────────────────────────────────────

@dataclass
class CostEstimate:
    low: float
    mid: float
    high: float
    real_cost_mid: float
    llm_provider: str
    breakdown: dict = field(default_factory=dict)


# ── Pure cost functions ──────────────────────────────────────────────────

def compute_llm_cost(
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
    llm_provider: str,
) -> float:
    """Pure function. No side effects."""
    rates = LLM_RATES.get(llm_provider, LLM_RATES["anthropic"])
    actual_input = max(0, input_tokens - cached_tokens)
    return (
        (actual_input / 1_000_000) * rates["input"]
        + (cached_tokens / 1_000_000) * rates["cache"]
        + (output_tokens / 1_000_000) * rates["output"]
    )


def compute_infra_cost(files_analyzed: int, rag_chunks: int) -> float:
    return files_analyzed * INFRA_COST_PER_FILE + rag_chunks * RAG_COST_PER_CHUNK


def estimate_cost(
    files_count: int,
    scope_type: str,
    llm_provider: str,
    plan: str,
    has_prior_analyses: bool = False,
) -> CostEstimate:
    """
    Heuristic estimate shown BEFORE analysis starts.
    Token estimation: ~3500 input tokens/file, ~900 output tokens/file.
    """
    tokens_input_est = files_count * 3500
    tokens_output_est = files_count * 900
    cached_est = int(tokens_input_est * 0.6) if has_prior_analyses else 0
    actual_input_est = tokens_input_est - cached_est

    llm_cost = compute_llm_cost(actual_input_est, cached_est, tokens_output_est, llm_provider)
    rag_chunks_est = files_count * 5
    infra_cost = compute_infra_cost(files_count, rag_chunks_est)
    real_cost = llm_cost + infra_cost
    margin = PLAN_MARGINS.get(plan, 3.0)
    client_cost = real_cost * margin

    no_cache_llm_cost = compute_llm_cost(tokens_input_est, 0, tokens_output_est, llm_provider)
    cache_savings = no_cache_llm_cost - llm_cost

    breakdown = {
        "tokens_input_est": tokens_input_est,
        "tokens_output_est": tokens_output_est,
        "tokens_cached_est": cached_est,
        "llm_cost_est": round(llm_cost, 6),
        "infra_cost_est": round(infra_cost, 6),
        "real_cost_est": round(real_cost, 6),
        "margin": margin,
        "client_cost_est": round(client_cost, 6),
        "prompt_cache_savings_est": round(cache_savings, 6),
    }

    return CostEstimate(
        low=round(client_cost * 0.7, 6),
        mid=round(client_cost, 6),
        high=round(client_cost * 1.4, 6),
        real_cost_mid=round(real_cost, 6),
        llm_provider=llm_provider,
        breakdown=breakdown,
    )


# ── Legacy helpers ───────────────────────────────────────────────────────

def _quantize_usd(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _compute_reservation_split(
    *,
    cost: int,
    credits_remaining: int,
    extra_balance_usd: Decimal,
    plan: str,
) -> tuple[int, Decimal, int]:
    plan_credits_used = min(max(0, credits_remaining), cost)
    credits_from_wallet = cost - plan_credits_used
    rate = Decimal(str(overage_rate_for_plan(plan)))
    usd_charged = _quantize_usd(rate * Decimal(credits_from_wallet))
    return plan_credits_used, usd_charged, credits_from_wallet


class InsufficientCreditsError(Exception):
    pass


# ── Main BillingGate ─────────────────────────────────────────────────────

class BillingGate:

    # ── check_and_reserve ────────────────────────────────────────────────

    async def check_and_reserve(
        self,
        tenant_id: str,
        analysis_type: str,
        *,
        scope_type: str | None = None,
        files_count: int = 0,
        llm_provider: str | None = None,
        has_prior_analyses: bool = False,
    ) -> tuple[str, dict]:
        """
        Reserve resources for an analysis. Returns (reservation_token, snapshot).

        When USE_TOKEN_BILLING is True, checks budget based on estimated real cost.
        When False, falls back to legacy credit reservation.
        """
        from apps.api.core.database import get_session_with_tenant
        from apps.api.models.auth import Tenant
        from sqlalchemy import select

        async with get_session_with_tenant(tenant_id) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
            tenant = result.scalar_one_or_none()

        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found.")

        if tenant.plan != "free" and tenant.stripe_subscription_status not in (
            "active", "trialing", "past_due", None
        ):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Subscription inactive. Please update your payment method.",
            )

        if not USE_TOKEN_BILLING:
            return await self._legacy_reserve(tenant_id, tenant, analysis_type)

        # ── Token-based reservation ──────────────────────────────────────
        effective_scope = scope_type or ("selection" if analysis_type == "quick" else "full_repo")
        effective_provider = llm_provider or DEFAULT_PROVIDER_PER_PLAN.get(tenant.plan, "cerebra_ai")

        if tenant.plan in ("free", "starter") and effective_provider == "anthropic":
            effective_provider = "cerebra_ai"

        est = estimate_cost(
            max(1, files_count),
            effective_scope,
            effective_provider,
            tenant.plan,
            has_prior_analyses,
        )

        included = PLAN_INCLUDED_REAL_COST.get(tenant.plan)
        used_real = float(tenant.real_cost_used_this_period or 0)
        if included is not None and tenant.plan == "free":
            if used_real + est.real_cost_mid > included:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=(
                        f"Monthly analysis budget reached (${used_real:.2f} of ${included:.2f} used). "
                        "Upgrade your plan to continue."
                    ),
                )

        token = secrets.token_urlsafe(16)
        snapshot = {
            "plan": tenant.plan,
            "scope_type": effective_scope,
            "llm_provider": effective_provider,
            "estimated_real_cost": est.real_cost_mid,
            "estimated_client_cost": est.mid,
            "margin": PLAN_MARGINS.get(tenant.plan, 3.0),
            "files_count": files_count,
            "created_at": datetime.now(timezone.utc).isoformat(),
            # Legacy compat
            "cost": LEGACY_ANALYSIS_COSTS.get(analysis_type, 3),
            "analysis_type": analysis_type,
        }
        reservation = {
            **snapshot,
            "tenant_id": tenant_id,
            "credits_at_reservation": tenant.credits_remaining,
        }

        redis = get_redis()
        await redis.setex(
            tenant_key(tenant_id, f"reservation:{token}"),
            RESERVATION_TTL,
            json.dumps(reservation),
        )

        # Insert cost_events row type=reserved
        try:
            from apps.api.models.analysis import CostEvent
            async with get_session_with_tenant(tenant_id) as session:
                pass  # job_id not known yet; event inserted by caller after job creation
        except Exception:
            pass

        # Still debit legacy credits for backwards compat during transition
        cost = LEGACY_ANALYSIS_COSTS.get(analysis_type, 3)
        extra_bal = Decimal(str(tenant.extra_balance_usd or 0))
        plan_credits_used, usd_charged, _ = _compute_reservation_split(
            cost=cost, credits_remaining=tenant.credits_remaining,
            extra_balance_usd=extra_bal, plan=tenant.plan,
        )
        async with get_session_with_tenant(tenant_id) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
            t = result.scalar_one()
            t.credits_remaining = t.credits_remaining - plan_credits_used
            t.extra_balance_usd = _quantize_usd(Decimal(str(t.extra_balance_usd or 0)) - usd_charged)

        log.info(
            "billing_reserved",
            tenant_id=tenant_id,
            scope_type=effective_scope,
            llm_provider=effective_provider,
            estimated_real_cost=est.real_cost_mid,
            estimated_client_cost=est.mid,
            token=token[:8],
        )
        return token, snapshot

    async def _legacy_reserve(
        self, tenant_id: str, tenant: object, analysis_type: str,
    ) -> tuple[str, dict]:
        from apps.api.core.database import get_session_with_tenant
        from apps.api.models.auth import Tenant
        from sqlalchemy import select

        cost = LEGACY_ANALYSIS_COSTS.get(analysis_type, 3)
        extra_bal = Decimal(str(tenant.extra_balance_usd or 0))
        plan_credits_used, usd_charged, credits_from_wallet = _compute_reservation_split(
            cost=cost, credits_remaining=tenant.credits_remaining,
            extra_balance_usd=extra_bal, plan=tenant.plan,
        )

        if extra_bal < usd_charged:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Insufficient credits. This analysis costs {cost} credits.",
            )

        token = secrets.token_urlsafe(16)
        snapshot = {
            "cost": cost, "plan_credits_used": plan_credits_used,
            "usd_charged": str(usd_charged), "credits_paid_from_wallet": credits_from_wallet,
            "plan": tenant.plan, "analysis_type": analysis_type,
        }
        reservation = {
            **snapshot, "tenant_id": tenant_id,
            "credits_at_reservation": tenant.credits_remaining,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        redis = get_redis()
        await redis.setex(
            tenant_key(tenant_id, f"reservation:{token}"),
            RESERVATION_TTL, json.dumps(reservation),
        )

        async with get_session_with_tenant(tenant_id) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
            t = result.scalar_one()
            t.credits_remaining = t.credits_remaining - plan_credits_used
            t.extra_balance_usd = _quantize_usd(Decimal(str(t.extra_balance_usd or 0)) - usd_charged)

        return token, snapshot

    # ── consume (called by post_report with real token counts) ───────────

    async def consume(
        self,
        reservation_token: str,
        job_id: str,
        tenant_id: str,
        *,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
        total_cached_tokens: int = 0,
        files_analyzed: int = 0,
        rag_chunks_retrieved: int = 0,
        llm_provider: str = "anthropic",
        actual_credits: int | None = None,
        credits_paid_from_wallet: int = 0,
    ) -> dict:
        """
        Mark analysis as consumed with real token costs.
        Returns the cost breakdown dict.
        """
        if reservation_token == "context_free":
            return {}

        redis = get_redis()
        raw = await redis.get(tenant_key(tenant_id, f"reservation:{reservation_token}"))
        if raw:
            reservation = json.loads(raw)
        else:
            log.warning("reservation_expired_recording_consumption", token=reservation_token[:8])
            reservation = {"plan": "unknown", "analysis_type": "full"}

        from apps.api.core.database import get_session_with_tenant
        from apps.api.models.auth import Tenant
        from apps.api.models.analysis import AnalysisJob, CostEvent
        from apps.api.models.billing import BillingEvent
        from sqlalchemy import select

        plan = reservation.get("plan") or "unknown"
        credits_paid_from_wallet = int(reservation.get("credits_paid_from_wallet") or credits_paid_from_wallet)

        if not USE_TOKEN_BILLING:
            creds = actual_credits or int(reservation.get("cost", 3))
            await self._legacy_consume(
                reservation_token, creds, job_id, tenant_id,
                credits_paid_from_wallet=credits_paid_from_wallet,
            )
            return {}

        # ── Token-based consumption ──────────────────────────────────────
        llm_cost = compute_llm_cost(total_input_tokens, total_cached_tokens, total_output_tokens, llm_provider)
        infra_cost = compute_infra_cost(files_analyzed, rag_chunks_retrieved)
        real_cost = llm_cost + infra_cost
        margin = PLAN_MARGINS.get(plan, 3.0)
        client_cost = real_cost * margin

        no_cache_cost = compute_llm_cost(total_input_tokens, 0, total_output_tokens, llm_provider)
        cache_savings = no_cache_cost - llm_cost

        cost_breakdown = {
            "llm_provider": llm_provider,
            "input_tokens": total_input_tokens,
            "input_tokens_cached": total_cached_tokens,
            "output_tokens": total_output_tokens,
            "llm_cost_usd": round(llm_cost, 6),
            "infra_cost_usd": round(infra_cost, 6),
            "real_cost_usd": round(real_cost, 6),
            "margin": margin,
            "client_cost_usd": round(client_cost, 6),
            "files_analyzed": files_analyzed,
            "rag_chunks": rag_chunks_retrieved,
            "prompt_cache_savings_usd": round(cache_savings, 6),
        }

        stripe_customer_id: str | None = None
        async with get_session_with_tenant(tenant_id) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
            tenant = result.scalar_one()
            tenant.real_cost_used_this_period = Decimal(str(float(tenant.real_cost_used_this_period or 0) + real_cost))

            # Legacy compat: still increment credits_used
            creds = actual_credits or int(reservation.get("cost", 3))
            tenant.credits_used_this_period += creds
            stripe_customer_id = tenant.stripe_customer_id
            included_budget = PLAN_INCLUDED_REAL_COST.get(plan)

            session.add(BillingEvent(
                tenant_id=uuid.UUID(tenant_id),
                job_id=uuid.UUID(job_id),
                event_type="consumed",
                credits_delta=-creds,
                usd_amount=Decimal(str(round(client_cost, 6))),
                description=f"Analysis {job_id[:8]} — ${client_cost:.4f} ({llm_provider})",
            ))

            session.add(CostEvent(
                job_id=uuid.UUID(job_id),
                tenant_id=uuid.UUID(tenant_id),
                event_type="final",
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cached_tokens=total_cached_tokens,
                llm_provider=llm_provider,
                cost_usd=Decimal(str(round(real_cost, 6))),
                cumulative_cost=Decimal(str(round(real_cost, 6))),
                metadata_json=cost_breakdown,
            ))

            # Update job cost columns
            job_result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)))
            job = job_result.scalar_one_or_none()
            if job:
                job.input_tokens = total_input_tokens
                job.output_tokens = total_output_tokens
                job.input_tokens_cached = total_cached_tokens
                job.llm_cost_usd = Decimal(str(round(llm_cost, 6)))
                job.infra_cost_usd = Decimal(str(round(infra_cost, 6)))
                job.total_cost_usd = Decimal(str(round(client_cost, 6)))
                job.margin_applied = Decimal(str(margin))
                job.credits_consumed = creds

        # Report overage to Stripe
        if plan != "free" and stripe_customer_id:
            remaining_included = max(0, float(included_budget or 0) - float(tenant.real_cost_used_this_period or 0))
            overage_real = max(0, real_cost - remaining_included) if included_budget else 0
            if overage_real > 0:
                overage_client = overage_real * margin
                from apps.api.billing.stripe_service import StripeService
                stripe_svc = StripeService()
                await stripe_svc.report_cost_usage(
                    tenant_id=tenant_id,
                    customer_id=stripe_customer_id,
                    cost_usd_cents=round(overage_client * 100),
                    job_id=job_id,
                )

        await redis.delete(tenant_key(tenant_id, f"reservation:{reservation_token}"))
        log.info(
            "billing_consumed",
            tenant_id=tenant_id, job_id=job_id,
            real_cost=round(real_cost, 6), client_cost=round(client_cost, 6),
            llm_provider=llm_provider,
        )
        return cost_breakdown

    async def _legacy_consume(
        self, reservation_token: str, actual_credits: int, job_id: str, tenant_id: str,
        *, credits_paid_from_wallet: int = 0,
    ) -> None:
        from apps.api.core.database import get_session_with_tenant
        from apps.api.models.auth import Tenant
        from apps.api.models.billing import BillingEvent
        from sqlalchemy import select

        redis = get_redis()
        raw = await redis.get(tenant_key(tenant_id, f"reservation:{reservation_token}"))
        if raw:
            reservation = json.loads(raw)
            credits_paid_from_wallet = int(reservation.get("credits_paid_from_wallet") or credits_paid_from_wallet)
        else:
            reservation = {"plan": "unknown", "analysis_type": "full"}

        stripe_customer_id = None
        plan_for_stripe = reservation.get("plan") or "unknown"

        async with get_session_with_tenant(tenant_id) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
            tenant = result.scalar_one()
            tenant.credits_used_this_period += actual_credits
            stripe_customer_id = tenant.stripe_customer_id
            plan_for_stripe = reservation.get("plan") or tenant.plan

            session.add(BillingEvent(
                tenant_id=uuid.UUID(tenant_id), job_id=uuid.UUID(job_id),
                event_type="consumed", credits_delta=-actual_credits,
                description=f"Analysis {job_id[:8]} completed ({reservation.get('analysis_type', 'unknown')})",
            ))

        if plan_for_stripe != "free" and stripe_customer_id:
            from apps.api.billing.stripe_service import StripeService
            stripe_svc = StripeService()
            await stripe_svc.report_usage(
                tenant_id=tenant_id, customer_id=stripe_customer_id,
                credits_consumed=actual_credits,
                plan_limit=settings.plan_credits.get(plan_for_stripe, 50),
                job_id=job_id, timestamp=datetime.now(timezone.utc),
                credits_paid_from_wallet=credits_paid_from_wallet,
            )

        await redis.delete(tenant_key(tenant_id, f"reservation:{reservation_token}"))

    # ── release ──────────────────────────────────────────────────────────

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

            session.add(BillingEvent(
                tenant_id=uuid.UUID(tenant_id), event_type="released",
                credits_delta=plan_credits_used, usd_amount=usd_charged,
                description="Credits refunded for failed analysis",
            ))

        await redis.delete(tenant_key(tenant_id, f"reservation:{reservation_token}"))
        log.info("credits_released", tenant_id=tenant_id, plan_credits_used=plan_credits_used)
