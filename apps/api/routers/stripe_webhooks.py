"""Stripe webhook endpoint with idempotency + direct billing processing."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import structlog
import stripe
from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import text

from apps.api.core.config import settings
from apps.api.core.database import AsyncSessionFactory, db_session_no_rls

log = structlog.get_logger(__name__)
router = APIRouter()


# ── Payload helpers ──────────────────────────────────────────────────────────

def _stripe_event_to_dict(event: object) -> dict:
    if isinstance(event, dict):
        return event
    to_dict = getattr(event, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    raise TypeError("Stripe event must be a dict or have to_dict()")


def _json_default(o: object) -> object:
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, UUID):
        return str(o)
    if isinstance(o, bytes):
        return o.decode("utf-8", errors="replace")
    raise TypeError(f"Cannot JSON-serialize {type(o)!r}")


def _json_safe(raw: dict) -> dict:
    return json.loads(json.dumps(raw, default=_json_default))


# ── Stripe API helpers ────────────────────────────────────────────────────────

def _subscription_metadata(subscription_id: str) -> dict:
    """Fetch Subscription.metadata from Stripe (sync — called before entering async DB context)."""
    if not subscription_id or not settings.stripe_secret_key:
        return {}
    stripe.api_key = settings.stripe_secret_key
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        return dict(sub.metadata or {})
    except Exception as e:
        log.warning("stripe_subscription_retrieve_failed", subscription_id=subscription_id, error=str(e))
        return {}


async def _tenant_id_by_customer(customer_id: str) -> str | None:
    """
    Last-resort lookup: find tenant by stripe_customer_id stored in DB.
    Uses db_session_no_rls — the 'sre' role has BYPASSRLS, so it can see all tenants.
    """
    if not customer_id:
        return None
    sql = text("SELECT id FROM tenants WHERE stripe_customer_id = :cid LIMIT 1")
    async with db_session_no_rls() as session:
        result = await session.execute(sql, {"cid": customer_id})
    row = result.fetchone()
    if row:
        log.info("stripe_tenant_found_by_customer", customer_id=customer_id, tenant_id=str(row[0]))
        return str(row[0])
    log.warning("stripe_tenant_not_found_by_customer", customer_id=customer_id)
    return None


# ── Database helpers ─────────────────────────────────────────────────────────

@asynccontextmanager
async def _rls_session(tenant_id: str):
    """
    Open a session with an explicit transaction and SET LOCAL so RLS reads the
    correct tenant.  AsyncSessionFactory.begin() owns exactly one transaction —
    no double-BEGIN, guaranteed COMMIT on clean exit / ROLLBACK on exception.
    """
    async with AsyncSessionFactory.begin() as session:
        await session.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))
        yield session


async def _patch_tenant(tenant_id: str, **field_updates) -> bool:
    """
    Load the Tenant ORM object via RLS-aware session and apply field_updates.
    ORM handles type coercion (enums, datetimes, decimals) so we avoid raw-SQL
    cast issues with PostgreSQL enum types.
    Returns True if the tenant row was found and patched.
    """
    import uuid as uuid_lib
    from sqlalchemy import select

    from apps.api.models.auth import Tenant

    async with _rls_session(tenant_id) as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == uuid_lib.UUID(tenant_id))
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            log.warning("stripe_tenant_not_found", tenant_id=tenant_id)
            return False
        for key, value in field_updates.items():
            setattr(tenant, key, value)
        # session.commit() is called automatically when _rls_session exits cleanly

    log.info("stripe_tenant_patched", tenant_id=tenant_id, fields=list(field_updates.keys()))
    return True


async def _add_billing_event(tenant_id: str, event_type: str, **kwargs) -> None:
    """Insert a BillingEvent row within an RLS-aware transaction."""
    from apps.api.models.billing import BillingEvent

    async with _rls_session(tenant_id) as session:
        session.add(BillingEvent(
            tenant_id=UUID(tenant_id),
            event_type=event_type,
            **kwargs,
        ))
        await session.flush()


async def _read_tenant_fields(tenant_id: str, *columns: str) -> tuple | None:
    """SELECT specific columns from tenants with RLS context. Returns a Row or None."""
    col_list = ", ".join(columns)
    sql = text(f"SELECT {col_list} FROM tenants WHERE id = :tid")  # noqa: S608
    async with _rls_session(tenant_id) as session:
        result = await session.execute(sql, {"tid": tenant_id})
    return result.fetchone()


# ── Event handlers ────────────────────────────────────────────────────────────

async def _handle_checkout_completed(event_dict: dict) -> None:
    sess = event_dict.get("data", {}).get("object", {})
    sm = sess.get("metadata") or {}
    mode = sess.get("mode")

    if mode == "payment" and sm.get("type") == "top_up":
        tenant_id = sm.get("tenant_id")
        if not tenant_id:
            cid = sess.get("customer")
            if cid:
                tenant_id = await _tenant_id_by_customer(cid)
        if not tenant_id:
            log.warning("stripe_topup_no_tenant", session_id=sess.get("id"))
            return
        try:
            UUID(str(tenant_id))
        except ValueError:
            log.warning("stripe_topup_invalid_tenant", tenant_id=tenant_id)
            return
        amount_total = sess.get("amount_total")
        if amount_total is None:
            log.warning("stripe_topup_no_amount", session_id=sess.get("id"))
            return
        amount_usd = Decimal(int(amount_total)) / Decimal(100)

        from sqlalchemy import select

        from apps.api.models.auth import Tenant
        from apps.api.models.billing import BillingEvent

        async with _rls_session(str(tenant_id)) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == UUID(str(tenant_id))))
            tenant = result.scalar_one_or_none()
            if not tenant:
                log.warning("stripe_topup_tenant_missing", tenant_id=tenant_id)
                return
            prev = tenant.extra_balance_usd or Decimal(0)
            tenant.extra_balance_usd = prev + amount_usd
            session.add(BillingEvent(
                tenant_id=tenant.id,
                event_type="wallet_credited",
                credits_delta=0,
                usd_amount=amount_usd,
                description=f"Wallet top-up (${amount_usd:.2f})",
            ))
        log.info("stripe_wallet_credited", tenant_id=tenant_id, amount=str(amount_usd))
        return

    if mode == "payment":
        log.debug("stripe_checkout_payment_not_topup", session_id=sess.get("id"))
        return

    tenant_id = sm.get("tenant_id")
    plan = sm.get("plan")
    subscription_id = sess.get("subscription")
    customer_id = sess.get("customer")

    # Fallback 1: read from Subscription.metadata (subscription_data.metadata in checkout)
    if (not tenant_id or not plan) and subscription_id:
        sub_meta = _subscription_metadata(subscription_id)
        tenant_id = tenant_id or sub_meta.get("tenant_id")
        plan = plan or sub_meta.get("plan")

    # Fallback 2: lookup by stripe_customer_id already stored in tenants table
    if not tenant_id and customer_id:
        tenant_id = await _tenant_id_by_customer(customer_id)

    if not tenant_id:
        log.warning("stripe_checkout_no_tenant_id", session_id=sess.get("id"), customer_id=customer_id)
        return

    plan = plan or "starter"
    credits = settings.plan_credits.get(plan, 300)
    log.info("stripe_checkout_activating", tenant_id=tenant_id, plan=plan, credits=credits)

    patched = await _patch_tenant(tenant_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        stripe_subscription_status="active",
        plan=plan,
        credits_remaining=credits,
        credits_monthly_limit=credits,
        credits_used_this_period=0,
    )
    if patched:
        await _add_billing_event(
            tenant_id, "subscription_started",
            credits_delta=credits,
            description=f"Upgraded to {plan} plan",
        )
        log.info("stripe_checkout_plan_activated", tenant_id=tenant_id, plan=plan)


async def _handle_invoice_payment_succeeded(event_dict: dict) -> None:
    invoice = event_dict.get("data", {}).get("object", {})
    subscription_id = invoice.get("subscription") or None
    customer_id = invoice.get("customer") or None

    sub_meta = _subscription_metadata(subscription_id) if subscription_id else {}
    tenant_id = sub_meta.get("tenant_id")
    plan = sub_meta.get("plan")

    # Fallback: lookup by stripe_customer_id stored in tenants table
    if not tenant_id and customer_id:
        tenant_id = await _tenant_id_by_customer(customer_id)

    if not tenant_id:
        log.warning("stripe_invoice_no_tenant",
                    subscription_id=subscription_id, customer_id=customer_id)
        return

    plan = plan or "starter"

    # Check if tenant already has this subscription (detect first-time link)
    existing = await _read_tenant_fields(tenant_id, "stripe_subscription_id", "credits_monthly_limit")
    is_first_link = existing is None or existing[0] != subscription_id

    period_end_dt = (
        datetime.fromtimestamp(int(invoice["period_end"]), tz=timezone.utc)
        if invoice.get("period_end") else None
    )
    credits = settings.plan_credits.get(plan, 300)
    monthly_limit = existing[1] if existing else credits

    if is_first_link:
        patched = await _patch_tenant(tenant_id,
            stripe_subscription_id=subscription_id,
            stripe_customer_id=invoice.get("customer"),
            stripe_subscription_status="active",
            plan=plan,
            credits_remaining=credits,
            credits_monthly_limit=credits,
            credits_used_this_period=0,
            **({"stripe_current_period_end": period_end_dt} if period_end_dt else {}),
        )
        if patched:
            await _add_billing_event(
                tenant_id, "subscription_started",
                credits_delta=credits,
                usd_amount=invoice.get("amount_paid", 0) / 100,
                description=f"Subscription linked from invoice — {plan}",
            )
    else:
        patched = await _patch_tenant(tenant_id,
            credits_used_this_period=0,
            credits_remaining=monthly_limit,
            **({"stripe_current_period_end": period_end_dt} if period_end_dt else {}),
        )
        if patched:
            await _add_billing_event(
                tenant_id, "period_renewed",
                credits_delta=monthly_limit,
                usd_amount=invoice.get("amount_paid", 0) / 100,
                description="Billing period renewed",
            )

    log.info("stripe_invoice_processed", tenant_id=tenant_id, plan=plan, first_link=is_first_link)


async def _handle_invoice_payment_failed(event_dict: dict) -> None:
    invoice = event_dict.get("data", {}).get("object", {})
    subscription_id = invoice.get("subscription")
    if not subscription_id:
        return
    tenant_id = _subscription_metadata(subscription_id).get("tenant_id")
    if not tenant_id:
        return
    await _patch_tenant(tenant_id, stripe_subscription_status="past_due")
    await _add_billing_event(tenant_id, "payment_failed", description="Payment failed — Stripe will retry")


async def _handle_subscription_deleted(event_dict: dict) -> None:
    sub = event_dict.get("data", {}).get("object", {})
    tenant_id = (sub.get("metadata") or {}).get("tenant_id")
    if not tenant_id:
        tenant_id = _subscription_metadata(sub.get("id", "")).get("tenant_id")
    if not tenant_id:
        return
    free_credits = settings.plan_credits.get("free", 50)
    await _patch_tenant(tenant_id,
        plan="free",
        stripe_subscription_status="canceled",
        credits_remaining=free_credits,
        credits_monthly_limit=free_credits,
    )
    await _add_billing_event(tenant_id, "subscription_canceled",
        description="Subscription canceled — downgraded to free")


async def _handle_subscription_updated(event_dict: dict) -> None:
    sub = event_dict.get("data", {}).get("object", {})
    tenant_id = (sub.get("metadata") or {}).get("tenant_id")
    if not tenant_id:
        tenant_id = _subscription_metadata(sub.get("id", "")).get("tenant_id")
    if not tenant_id:
        return
    updates: dict = {}
    if sub.get("status"):
        updates["stripe_subscription_status"] = sub["status"]
    if sub.get("current_period_end"):
        updates["stripe_current_period_end"] = datetime.fromtimestamp(
            int(sub["current_period_end"]), tz=timezone.utc
        )
    if updates:
        await _patch_tenant(tenant_id, **updates)


_HANDLERS = {
    "checkout.session.completed": _handle_checkout_completed,
    "invoice.payment_succeeded": _handle_invoice_payment_succeeded,
    "invoice.payment_failed": _handle_invoice_payment_failed,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "customer.subscription.updated": _handle_subscription_updated,
}


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
) -> dict:
    """
    Receive Stripe webhook events.
    1. Verify signature.
    2. Deduplicate via stripe_events (idempotency).
    3. Process billing update directly — no Celery dependency.
    """
    payload_bytes = await request.body()

    if not settings.stripe_webhook_secret:
        log.warning("stripe_webhook_secret_not_configured")
        return {"status": "skipped"}

    try:
        event = stripe.Webhook.construct_event(
            payload_bytes, stripe_signature, settings.stripe_webhook_secret
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook error: {e}")

    event_id = event["id"]
    event_type = event["type"]
    log.info("stripe_webhook_received", event_id=event_id, event_type=event_type)

    event_dict = _json_safe(_stripe_event_to_dict(event))

    # ── Idempotency ──────────────────────────────────────────────────────────
    async with db_session_no_rls() as session:
        from apps.api.models.billing import StripeEvent
        stmt = pg_insert(StripeEvent).values(
            id=event_id,
            event_type=event_type,
            payload=event_dict,
        ).on_conflict_do_nothing(index_elements=["id"])
        result = await session.execute(stmt)

    if result.rowcount == 0:
        log.info("stripe_webhook_duplicate", event_id=event_id)
        return {"status": "already_processed"}

    # ── Process billing update ───────────────────────────────────────────────
    handler = _HANDLERS.get(event_type)
    if handler:
        try:
            await handler(event_dict)
        except Exception as e:
            # Log but don't return 5xx — Stripe would retry causing duplicates.
            log.error(
                "stripe_event_handler_failed",
                event_id=event_id,
                event_type=event_type,
                error=str(e),
                exc_info=True,
            )
    else:
        log.debug("stripe_event_unhandled", event_type=event_type)

    return {"status": "accepted", "event_id": event_id}
