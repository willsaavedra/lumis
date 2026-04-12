"""Celery task definitions."""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime, timezone

import structlog

from apps.worker.celery_app import celery_app

log = structlog.get_logger(__name__)

_ANALYSIS_WAIT_TIMEOUT_SEC = float(os.environ.get("ANALYSIS_AGENT_WAIT_TIMEOUT_SEC", "1800"))


@celery_app.task(
    bind=True,
    name="apps.worker.tasks.run_analysis",
    max_retries=2,
    soft_time_limit=2400,   # 40 minutes: raise SoftTimeLimitExceeded
    time_limit=2700,         # 45 minutes: SIGKILL hard stop
)
def run_analysis(self, job_id: str, reservation_token: str) -> dict:
    """
    Enqueues analysis on the Lumis Agent HTTP service and waits until the job
    finishes in the database (completed / failed). The graph runs in the agent process.
    """
    log.info("analysis_task_started", job_id=job_id)

    from billiard.exceptions import SoftTimeLimitExceeded

    async def _run():
        try:
            await _update_job_status(job_id, "running")
            await _trigger_agent_analysis(job_id)
            terminal = await _poll_job_until_terminal(job_id, timeout_sec=_ANALYSIS_WAIT_TIMEOUT_SEC)
        except Exception as e:
            log.error("analysis_task_failed", job_id=job_id, error=str(e))
            await _publish_analysis_failed_redis(job_id, str(e))
            await _maybe_mark_job_failed_if_running(job_id, str(e))
            await _release_credits(reservation_token, job_id)
            raise

        if terminal == "completed":
            await _consume_credits(job_id, reservation_token)
            log.info("analysis_task_completed", job_id=job_id)
            return {"status": "completed", "job_id": job_id}
        if terminal == "failed":
            await _release_credits(reservation_token, job_id)
            raise RuntimeError("Analysis failed — see job error_message")

        await _update_job_status(job_id, "failed", "Analysis timed out waiting for agent")
        await _release_credits(reservation_token, job_id)
        raise TimeoutError(f"Analysis did not complete within {_ANALYSIS_WAIT_TIMEOUT_SEC}s")

    try:
        return asyncio.run(_run())
    except SoftTimeLimitExceeded:
        log.error("analysis_task_timeout", job_id=job_id, soft_limit_sec=2400)
        asyncio.run(_publish_analysis_failed_redis(job_id, "Analysis timed out (worker soft limit)"))
        asyncio.run(_maybe_mark_job_failed_if_running(job_id, "Analysis timed out (worker soft limit)"))
        asyncio.run(_release_credits(reservation_token, job_id))
        raise


@celery_app.task(
    bind=True,
    name="apps.worker.tasks.create_fix_pr",
    max_retries=1,
    # Fix PR clones the repo, calls the LLM per-file (≤120 s each), pushes a branch,
    # and opens a GitHub PR — well above the 10-minute global default.
    soft_time_limit=1800,   # 30 minutes: raise SoftTimeLimitExceeded
    time_limit=2100,         # 35 minutes: SIGKILL hard stop
)
def create_fix_pr(self, job_id: str) -> dict:
    """Generate code fixes with Claude and open a GitHub PR."""
    from billiard.exceptions import SoftTimeLimitExceeded

    log.info("fix_pr_task_started", job_id=job_id)

    async def _run():
        from apps.api.services.analysis_notifications import notify_fix_pr_created
        from apps.api.services.fix_pr_service import create_fix_pr as _create_fix_pr
        try:
            pr_url = await _create_fix_pr(job_id)
            await _save_pr_url(job_id, pr_url)
            try:
                await notify_fix_pr_created(job_id=job_id, pr_url=pr_url)
            except Exception:
                log.exception("notify_fix_pr_created_failed", job_id=job_id)
            return {"status": "created", "pr_url": pr_url}
        except Exception as exc:
            log.exception("fix_pr_task_failed", job_id=job_id)
            reason = str(exc)[:500] if str(exc) else "Unknown error"
            await _clear_fix_pr_enqueue(job_id, error_reason=reason)
            raise

    try:
        return asyncio.run(_run())
    except SoftTimeLimitExceeded:
        # Signal fires inside the asyncio selector — it escapes asyncio.run() without
        # going through the inner except block, so we must clean up here.
        log.error("fix_pr_task_timeout", job_id=job_id, soft_limit_sec=1800)
        asyncio.run(_clear_fix_pr_enqueue(job_id))
        raise


@celery_app.task(bind=True, name="apps.worker.tasks.scan_repo_context", max_retries=1)
def scan_repo_context(self, repo_id: str) -> dict:
    """Fetch README and .md files from the repo and store as context_summary."""
    log.info("scan_repo_context_started", repo_id=repo_id)

    async def _run():
        from apps.api.core.database import AsyncSessionFactory
        from apps.api.models.scm import Repository, ScmConnection
        from sqlalchemy import select

        async with AsyncSessionFactory() as session:
            repo = (await session.execute(
                select(Repository).where(Repository.id == uuid.UUID(repo_id))
            )).scalar_one_or_none()

            if not repo:
                log.error("scan_context_repo_not_found", repo_id=repo_id)
                return {"status": "error", "detail": "repo not found"}

            connection = None
            if repo.scm_connection_id:
                connection = (await session.execute(
                    select(ScmConnection).where(ScmConnection.id == repo.scm_connection_id)
                )).scalar_one_or_none()

        installation_id = connection.installation_id if connection else None
        scm_type = connection.scm_type if connection else "github"
        summary = await _fetch_repo_context(
            repo.full_name,
            installation_id,
            scm_type=scm_type,
            default_branch=repo.default_branch,
            connection=connection,
        )

        async with AsyncSessionFactory() as session:
            repo = (await session.execute(
                select(Repository).where(Repository.id == uuid.UUID(repo_id))
            )).scalar_one_or_none()
            if repo:
                repo.context_summary = summary
            await session.commit()

        log.info("scan_repo_context_completed", repo_id=repo_id, summary_len=len(summary or ""))
        return {"status": "completed", "repo_id": repo_id}

    return asyncio.run(_run())


async def _fetch_repo_context(
    full_name: str,
    installation_id: str | None,
    *,
    scm_type: str = "github",
    default_branch: str = "main",
    connection=None,
) -> str:
    """Fetch README snippets from GitHub, GitLab, or Bitbucket APIs."""
    import httpx

    if scm_type == "gitlab" and connection and connection.encrypted_token:
        try:
            from apps.api.core.security import decrypt_scm_token
            from apps.api.scm import gitlab as gl

            tok = decrypt_scm_token(connection.encrypted_token)
            if tok:
                for path in ("README.md", "readme.md"):
                    text = await gl.get_raw_file(tok, full_name, path, default_branch)
                    if text:
                        return f"### {path}\n{text[:4000]}"
        except Exception as e:
            log.warning("gitlab_context_fetch_failed", error=str(e))
        return ""

    if scm_type == "bitbucket" and connection and connection.encrypted_token:
        # Optional: fetch via raw content URL — omitted for brevity
        return ""

    token = None
    if installation_id and scm_type == "github":
        try:
            from apps.api.scm.github import GitHubTokenManager

            token = await GitHubTokenManager().get_installation_token(int(installation_id))
        except Exception as e:
            log.warning("github_token_fetch_failed", error=str(e))

    if not token:
        return ""

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    parts: list[str] = []
    candidate_paths = ["README.md", "readme.md", "ARCHITECTURE.md", "docs/README.md", "CONTRIBUTING.md"]

    async with httpx.AsyncClient(timeout=15) as client:
        for path in candidate_paths:
            try:
                resp = await client.get(
                    f"https://api.github.com/repos/{full_name}/contents/{path}",
                    headers=headers,
                )
                if resp.status_code == 200:
                    content = resp.text[:4000]
                    parts.append(f"### {path}\n{content}")
                    if len(parts) >= 2:
                        break
            except Exception:
                continue

    return "\n\n".join(parts)


async def _save_pr_url(job_id: str, pr_url: str) -> None:
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob
    from sqlalchemy import select

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)))
        job = result.scalar_one_or_none()
        if job:
            job.fix_pr_url = pr_url
            job.fix_pr_enqueued_at = None
            job.fix_pr_error = None
        await session.commit()


async def _clear_fix_pr_enqueue(job_id: str, *, error_reason: str | None = None) -> None:
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob
    from sqlalchemy import select

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)))
        job = result.scalar_one_or_none()
        if job:
            job.fix_pr_enqueued_at = None
            if error_reason:
                job.fix_pr_error = error_reason
        await session.commit()


@celery_app.task(name="apps.worker.tasks.process_stripe_event")
def process_stripe_event(event_id: str, event_type: str, payload: dict) -> None:
    """Process a Stripe webhook event."""
    log.info("processing_stripe_event", event_id=event_id, event_type=event_type)
    try:
        asyncio.run(_handle_stripe_event(event_id, event_type, payload))
    except Exception as e:
        log.error("stripe_event_processing_failed", event_id=event_id, error=str(e))
        raise


@celery_app.task(name="apps.worker.tasks.run_scheduled_analyses")
def run_scheduled_analyses() -> None:
    """Celery Beat task: trigger scheduled analyses for due repositories."""
    asyncio.run(_schedule_due_analyses())


async def _db_session():
    from apps.api.core.database import AsyncSessionFactory
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _trigger_agent_analysis(job_id: str) -> None:
    """POST /analyze/{job_id} on the Lumis Agent service (graph runs there)."""
    import httpx
    from apps.api.core.config import settings

    url = f"{settings.agent_base_url.rstrip('/')}/analyze/{job_id}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url)
        resp.raise_for_status()


async def _poll_job_until_terminal(job_id: str, *, timeout_sec: float) -> str | None:
    """Return 'completed', 'failed', or None on timeout."""
    from sqlalchemy import select

    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob

    deadline = time.monotonic() + timeout_sec
    jid = uuid.UUID(job_id)
    while time.monotonic() < deadline:
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(AnalysisJob.status).where(AnalysisJob.id == jid))
            st = result.scalar_one_or_none()
        if st in ("completed", "failed"):
            return st
        await asyncio.sleep(2.0)
    return None


async def _maybe_mark_job_failed_if_running(job_id: str, err: str) -> None:
    """If HTTP trigger failed early, job may still be 'running' — mark failed for UX."""
    from sqlalchemy import select

    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob

    msg = (err or "Analysis failed.")[:2000]
    async with AsyncSessionFactory() as session:
        result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)))
        job = result.scalar_one_or_none()
        if job and job.status == "running":
            job.status = "failed"
            job.error_message = msg
            job.completed_at = datetime.now(timezone.utc)
        await session.commit()


async def _publish_analysis_failed_redis(job_id: str, error_message: str) -> None:
    """Notify SSE subscribers that the analysis failed (worker catch path).

    Publishes directly to Redis — does NOT import from apps.agent to keep
    the worker process fully decoupled from the agent package.
    Any communication with the agent must go through the agent HTTP API.
    """
    import json

    import redis.asyncio as aioredis

    from apps.api.core.config import settings
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob
    from sqlalchemy import select

    _TIMELINE_TTL_SEC = 604800  # 7 days — same as agent's base.py

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()
        if not job:
            return

        msg = (error_message or "Analysis failed.")[:2000]
        tenant_id = str(job.tenant_id)

        event_obj = {
            "event_type": "step",
            "stage": "failed",
            "progress_pct": 0,
            "message": msg,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        event = json.dumps(event_obj, ensure_ascii=False)
        channel = f"t:{tenant_id}:analysis:{job_id}:progress"
        timeline_key = f"t:{tenant_id}:analysis:{job_id}:timeline"

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await r.publish(channel, event)
            await r.rpush(timeline_key, event)
            await r.expire(timeline_key, _TIMELINE_TTL_SEC)
        finally:
            await r.aclose()
    except Exception as ex:
        log.warning("publish_analysis_failed_redis_failed", job_id=job_id, error=str(ex))


async def _update_job_status(job_id: str, status: str, error: str | None = None) -> None:
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob
    from sqlalchemy import select

    async with AsyncSessionFactory() as session:
        try:
            result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()
            if job:
                job.status = status
                if status == "running":
                    job.started_at = datetime.now(timezone.utc)
                if status == "completed":
                    job.completed_at = datetime.now(timezone.utc)
                if error:
                    job.error_message = error
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _consume_credits(job_id: str, reservation_token: str) -> None:
    from apps.api.billing.billing_gate import BillingGate
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob
    from sqlalchemy import select

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)))
        job = result.scalar_one_or_none()

    if job:
        gate = BillingGate()
        actual_credits = job.credits_consumed or job.credits_reserved
        wallet_credits = 0
        if job.billing_reservation:
            wallet_credits = int(job.billing_reservation.get("credits_paid_from_wallet") or 0)
        await gate.consume(
            reservation_token=reservation_token,
            actual_credits=actual_credits,
            job_id=job_id,
            tenant_id=str(job.tenant_id),
            credits_paid_from_wallet=wallet_credits,
        )


async def _release_credits(reservation_token: str, job_id: str) -> None:
    try:
        from apps.api.billing.billing_gate import BillingGate
        from apps.api.core.database import AsyncSessionFactory
        from apps.api.models.analysis import AnalysisJob
        from sqlalchemy import select

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()

        if job:
            gate = BillingGate()
            await gate.release(
                reservation_token,
                str(job.tenant_id),
                job.credits_reserved,
                billing_snapshot=job.billing_reservation,
            )
    except Exception as e:
        log.error("release_credits_failed", error=str(e))


def _tenant_plan_from_stripe_subscription(subscription_id: str | None) -> tuple[str | None, str]:
    """Read tenant_id + plan from Subscription.metadata (Checkout subscription_data.metadata)."""
    if not subscription_id:
        return None, "starter"
    import stripe
    from apps.api.core.config import settings
    if not settings.stripe_secret_key:
        return None, "starter"
    stripe.api_key = settings.stripe_secret_key
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        meta = sub.metadata or {}
        return meta.get("tenant_id"), meta.get("plan") or "starter"
    except Exception as e:
        log.warning("stripe_subscription_retrieve_failed", subscription_id=subscription_id, error=str(e))
        return None, "starter"


def _tenant_id_from_subscription_object(sub: dict | None) -> str | None:
    """tenant_id from webhook Subscription object, or Stripe API if metadata missing."""
    if not sub:
        return None
    tid = (sub.get("metadata") or {}).get("tenant_id")
    if tid:
        return tid
    sid = sub.get("id")
    if sid:
        tid2, _ = _tenant_plan_from_stripe_subscription(sid)
        return tid2
    return None


async def _handle_stripe_event(event_id: str, event_type: str, payload: dict) -> None:
    """Process Stripe events and update tenant state.

    Must use get_session_with_tenant: RLS hides all tenant rows unless app.tenant_id is set.
    Plain AsyncSessionFactory() updates were no-ops (0 rows).
    """
    from decimal import Decimal

    from apps.api.core.database import get_session_with_tenant
    from apps.api.models.auth import Tenant
    from apps.api.models.billing import BillingEvent
    from apps.api.core.config import settings
    from sqlalchemy import select
    import uuid as uuid_lib

    if event_type == "checkout.session.completed":
        sess = payload.get("data", {}).get("object", {})
        sm = sess.get("metadata") or {}
        mode = sess.get("mode")

        if mode == "payment" and sm.get("type") == "top_up":
            tenant_id = sm.get("tenant_id")
            amount_total = sess.get("amount_total")
            if not tenant_id or amount_total is None:
                log.warning("stripe_topup_incomplete_worker", event_id=event_id, session_id=sess.get("id"))
                return
            try:
                uuid_lib.UUID(str(tenant_id))
            except ValueError:
                log.warning("stripe_topup_invalid_tenant_worker", tenant_id=tenant_id)
                return
            amount_usd = Decimal(int(amount_total)) / Decimal(100)
            async with get_session_with_tenant(str(tenant_id)) as session:
                result = await session.execute(
                    select(Tenant).where(Tenant.id == uuid_lib.UUID(str(tenant_id)))
                )
                tenant = result.scalar_one_or_none()
                if not tenant:
                    log.warning("stripe_topup_tenant_not_found_worker", tenant_id=tenant_id)
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
            log.info("stripe_wallet_credited_worker", tenant_id=tenant_id, amount=str(amount_usd))
            return

        if mode == "payment":
            log.debug("stripe_checkout_payment_skipped_worker", session_id=sess.get("id"))
            return

        tenant_id = sm.get("tenant_id")
        plan = sm.get("plan", "starter")
        subscription_id = sess.get("subscription")
        customer_id = sess.get("customer")

        if not tenant_id and subscription_id:
            sid = subscription_id if isinstance(subscription_id, str) else subscription_id.get("id")
            tid, pl = _tenant_plan_from_stripe_subscription(sid)
            tenant_id = tid or tenant_id
            if pl:
                plan = pl

        if not tenant_id:
            log.warning("stripe_checkout_missing_tenant_id", event_id=event_id, session_id=sess.get("id"))
            return
        try:
            uuid_lib.UUID(str(tenant_id))
        except ValueError:
            log.warning("stripe_checkout_invalid_tenant_id", tenant_id=tenant_id)
            return

        async with get_session_with_tenant(str(tenant_id)) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid_lib.UUID(str(tenant_id))))
            tenant = result.scalar_one_or_none()
            if not tenant:
                log.warning("stripe_checkout_tenant_not_found", tenant_id=tenant_id)
                return
            tenant.stripe_customer_id = customer_id
            tenant.stripe_subscription_id = subscription_id
            tenant.stripe_subscription_status = "active"
            tenant.plan = plan
            tenant.credits_remaining = settings.plan_credits.get(plan, 300)
            tenant.credits_monthly_limit = settings.plan_credits.get(plan, 300)
            tenant.credits_used_this_period = 0
            session.add(BillingEvent(
                tenant_id=tenant.id,
                event_type="subscription_started",
                credits_delta=settings.plan_credits.get(plan, 300),
                description=f"Upgraded to {plan} plan",
            ))
        return

    if event_type == "invoice.payment_succeeded":
        invoice = payload.get("data", {}).get("object", {})
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return
        tid, plan = _tenant_plan_from_stripe_subscription(subscription_id)
        if not tid:
            log.warning(
                "stripe_invoice_missing_tenant_metadata",
                event_id=event_id,
                subscription_id=subscription_id,
            )
            return

        async with get_session_with_tenant(str(tid)) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid_lib.UUID(str(tid))))
            tenant = result.scalar_one_or_none()
            if not tenant:
                log.warning("stripe_invoice_tenant_not_found", tenant_id=tid)
                return

            linked_from_invoice = tenant.stripe_subscription_id != subscription_id
            if linked_from_invoice:
                tenant.stripe_subscription_id = subscription_id
                cust = invoice.get("customer")
                if cust:
                    tenant.stripe_customer_id = cust
                tenant.stripe_subscription_status = "active"
                tenant.plan = plan
                tenant.credits_remaining = settings.plan_credits.get(plan, 300)
                tenant.credits_monthly_limit = settings.plan_credits.get(plan, 300)
                tenant.credits_used_this_period = 0
                session.add(BillingEvent(
                    tenant_id=tenant.id,
                    event_type="subscription_started",
                    credits_delta=settings.plan_credits.get(plan, 300),
                    description=f"Subscription linked from invoice — {plan}",
                ))

            period_end = invoice.get("period_end")
            if period_end:
                tenant.stripe_current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)
            if not linked_from_invoice:
                tenant.credits_used_this_period = 0
                tenant.credits_remaining = tenant.credits_monthly_limit
                session.add(BillingEvent(
                    tenant_id=tenant.id,
                    event_type="period_renewed",
                    credits_delta=tenant.credits_monthly_limit,
                    usd_amount=invoice.get("amount_paid", 0) / 100,
                    description="Billing period renewed",
                ))
        return

    if event_type == "invoice.payment_failed":
        invoice = payload.get("data", {}).get("object", {})
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return
        tid, _ = _tenant_plan_from_stripe_subscription(subscription_id)
        if not tid:
            return
        async with get_session_with_tenant(str(tid)) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid_lib.UUID(str(tid))))
            tenant = result.scalar_one_or_none()
            if tenant:
                tenant.stripe_subscription_status = "past_due"
                session.add(BillingEvent(
                    tenant_id=tenant.id,
                    event_type="payment_failed",
                    description="Payment failed — Stripe will retry",
                ))
        return

    if event_type == "customer.subscription.deleted":
        sub = payload.get("data", {}).get("object", {})
        tenant_id = _tenant_id_from_subscription_object(sub)
        if not tenant_id:
            log.warning("stripe_subscription_deleted_no_tenant", event_id=event_id)
            return
        async with get_session_with_tenant(str(tenant_id)) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid_lib.UUID(str(tenant_id))))
            tenant = result.scalar_one_or_none()
            if tenant:
                tenant.plan = "free"
                tenant.stripe_subscription_status = "canceled"
                tenant.credits_remaining = 50
                tenant.credits_monthly_limit = 50
                session.add(BillingEvent(
                    tenant_id=tenant.id,
                    event_type="subscription_canceled",
                    description="Subscription canceled — downgraded to free",
                ))
        return

    if event_type == "customer.subscription.updated":
        sub = payload.get("data", {}).get("object", {})
        tenant_id = _tenant_id_from_subscription_object(sub)
        if not tenant_id:
            log.warning("stripe_subscription_updated_no_tenant", event_id=event_id)
            return
        async with get_session_with_tenant(str(tenant_id)) as session:
            result = await session.execute(select(Tenant).where(Tenant.id == uuid_lib.UUID(str(tenant_id))))
            tenant = result.scalar_one_or_none()
            if tenant:
                tenant.stripe_subscription_status = sub.get("status")
                period_end = sub.get("current_period_end")
                if period_end:
                    tenant.stripe_current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)
        return


async def _schedule_due_analyses() -> None:
    """Find repositories due for scheduled analysis and enqueue jobs."""
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.scm import Repository
    from apps.api.services.analysis_service import enqueue_manual_analysis
    from sqlalchemy import select, and_

    async with AsyncSessionFactory() as session:
        now = datetime.now(timezone.utc)
        result = await session.execute(
            select(Repository).where(
                and_(
                    Repository.is_active == True,
                    Repository.schedule_enabled == True,
                    Repository.next_run_at <= now,
                )
            )
        )
        repos = result.scalars().all()

    for repo in repos:
        try:
            async with AsyncSessionFactory() as session:
                job = await enqueue_manual_analysis(
                    session,
                    tenant_id=str(repo.tenant_id),
                    repo_id=str(repo.id),
                    ref=repo.schedule_ref,
                    analysis_type="full",
                )
                # Update next_run_at (simplified: add 7 days for weekly)
                from datetime import timedelta
                repo.next_run_at = now + timedelta(days=7)
                log.info("scheduled_analysis_enqueued", repo=repo.full_name, job_id=str(job.id))
        except Exception as e:
            log.warning("scheduled_analysis_failed", repo=repo.full_name, error=str(e))
