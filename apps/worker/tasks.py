"""Celery task definitions."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import structlog

from apps.worker.celery_app import celery_app

log = structlog.get_logger(__name__)


@celery_app.task(bind=True, name="apps.worker.tasks.run_analysis", max_retries=2)
def run_analysis(self, job_id: str, reservation_token: str) -> dict:
    """
    Main analysis task. Calls the LangGraph agent asynchronously.
    All async work runs in a single event loop to avoid Redis loop conflicts.
    """
    import time as _time
    import structlog as _structlog
    _structlog.contextvars.clear_contextvars()
    _structlog.contextvars.bind_contextvars(job_id=job_id, task="run_analysis")
    log.info("analysis_task_started", job_id=job_id)
    _task_start = _time.monotonic()

    async def _run():
        import uuid as _uuid
        import httpx
        from apps.api.core.database import AsyncSessionFactory
        from apps.api.core.config import settings
        from apps.api.models.analysis import AnalysisJob, AnalysisResult, Finding as FindingModel
        from apps.api.models.scm import Repository, ScmConnection
        from sqlalchemy import select

        # Load job + repo to build payload for TS agent
        async with AsyncSessionFactory() as _s:
            _job = (await _s.execute(select(AnalysisJob).where(AnalysisJob.id == _uuid.UUID(job_id)))).scalar_one_or_none()
            if not _job:
                raise ValueError(f"Job {job_id} not found")
            _repo = (await _s.execute(select(Repository).where(Repository.id == _job.repo_id))).scalar_one_or_none()
            _conn = None
            if _repo and _repo.scm_connection_id:
                _conn = (await _s.execute(select(ScmConnection).where(ScmConnection.id == _repo.scm_connection_id))).scalar_one_or_none()

        _structlog.contextvars.bind_contextvars(
            tenant_id=str(_job.tenant_id),
            analysis_type=_job.analysis_type,
            llm_provider=getattr(_job, "llm_provider", "anthropic"),
            repo_id=str(_job.repo_id),
        )

        try:
            await _update_job_status(job_id, "running")

            payload = await _build_analysis_payload(_job, _repo, _conn, settings)

            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
                resp = await client.post(f"{settings.ts_agent_url}/analyze", json=payload)
                resp.raise_for_status()
                result = resp.json()

            await _persist_analysis_result(job_id, str(_job.tenant_id), result)

            await _update_job_status(job_id, "completed")
            await _consume_credits(job_id, reservation_token)

            findings_count = len(result.get("findings", []))
            score_global = result.get("scores", {}).get("global")

            log.info(
                "analysis_task_completed",
                job_id=job_id,
                findings_count=findings_count,
                score_global=score_global,
                duration_ms=round((_time.monotonic() - _task_start) * 1000),
            )
            return {"status": "completed", "job_id": job_id}

        except Exception as e:
            log.error(
                "analysis_task_failed",
                job_id=job_id,
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=round((_time.monotonic() - _task_start) * 1000),
            )
            await _publish_analysis_failed_redis(job_id, str(e))
            await _update_job_status(job_id, "failed", str(e))
            await _release_credits(reservation_token, job_id)
            raise

    return asyncio.run(_run())


@celery_app.task(bind=True, name="apps.worker.tasks.create_fix_pr", max_retries=1)
def create_fix_pr(self, job_id: str) -> dict:
    """Generate code fixes with Claude and open a GitHub PR."""
    import time as _time
    import structlog as _structlog
    _structlog.contextvars.clear_contextvars()
    _structlog.contextvars.bind_contextvars(job_id=job_id, task="create_fix_pr")
    log.info("fix_pr_task_started", job_id=job_id)
    _task_start = _time.monotonic()

    async def _run():
        import uuid as _uuid
        from apps.api.core.database import AsyncSessionFactory
        from apps.api.models.analysis import AnalysisJob
        from sqlalchemy import select

        # Bind llm_provider from the job record
        try:
            async with AsyncSessionFactory() as _s:
                _job = (await _s.execute(select(AnalysisJob).where(AnalysisJob.id == _uuid.UUID(job_id)))).scalar_one_or_none()
            if _job:
                _structlog.contextvars.bind_contextvars(
                    llm_provider=getattr(_job, "llm_provider", "anthropic"),
                    tenant_id=str(_job.tenant_id),
                )
        except Exception:
            pass

        from apps.api.services.fix_pr_service import create_fix_pr as _create_fix_pr
        try:
            pr_url = await _create_fix_pr(job_id)
            await _save_pr_url(job_id, pr_url)
            log.info("fix_pr_task_completed", job_id=job_id, pr_url=pr_url, duration_ms=round((_time.monotonic() - _task_start) * 1000))
            return {"status": "created", "pr_url": pr_url}
        except Exception:
            log.exception("fix_pr_task_failed", job_id=job_id, duration_ms=round((_time.monotonic() - _task_start) * 1000))
            await _clear_fix_pr_enqueue(job_id)
            raise

    return asyncio.run(_run())


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


async def _build_analysis_payload(job, repo, conn, settings) -> dict:
    """Build the AnalysisRequest payload for the TS agent from DB records."""
    installation_id = conn.installation_id if conn else None
    scm_type = (conn.scm_type if conn else "github") or "github"

    full_name = repo.full_name if repo else ""
    clone_url = ""
    if repo:
        clone_url = repo.clone_url or ""
        if not clone_url:
            if scm_type == "gitlab":
                base = settings.gitlab_base_url.rstrip("/")
                clone_url = f"{base}/{full_name}.git"
            elif scm_type == "bitbucket":
                clone_url = f"https://bitbucket.org/{full_name}.git"
            else:
                clone_url = f"https://github.com/{full_name}.git"

    # Resolve authenticated clone URL so the TS agent can clone without Python deps
    if installation_id and scm_type == "github":
        try:
            from apps.api.scm.github import GitHubTokenManager
            token = await GitHubTokenManager().get_installation_token(int(installation_id))
            clone_url = f"https://x-access-token:{token}@github.com/{full_name}.git"
        except Exception as e:
            log.warning("token_fetch_failed_using_public_url", error=str(e))
    elif scm_type in ("gitlab", "bitbucket") and conn:
        try:
            from apps.api.core.security import decrypt_scm_token
            raw = decrypt_scm_token(conn.encrypted_token) if conn.encrypted_token else None
            if raw:
                if scm_type == "gitlab":
                    from apps.api.scm.gitlab import authenticated_clone_url
                    clone_url = authenticated_clone_url(raw, clone_url, full_name)
                else:
                    from apps.api.scm.bitbucket import authenticated_clone_url as bb_auth
                    clone_url = bb_auth(raw, clone_url, full_name)
        except Exception as e:
            log.warning("oauth_clone_url_failed", error=str(e), scm_type=scm_type)

    repo_context = {}
    if repo:
        repo_context = {
            "repoType": getattr(repo, "repo_type", None) or "",
            "language": getattr(repo, "language", None) or "",
            "observabilityBackend": getattr(repo, "observability_backend", None),
            "contextSummary": getattr(repo, "context_summary", None),
        }

    return {
        "jobId": str(job.id),
        "tenantId": str(job.tenant_id),
        "repoId": str(job.repo_id),
        "repoFullName": full_name,
        "cloneUrl": clone_url,
        "ref": job.branch_ref or (repo.default_branch if repo else "main"),
        "scmType": scm_type,
        "changedFiles": job.changed_files.get("files", []) if job.changed_files else None,
        "analysisType": job.analysis_type,
        "llmProvider": getattr(job, "llm_provider", "anthropic"),
        "repoContext": repo_context,
    }


async def _persist_analysis_result(job_id: str, tenant_id: str, result: dict) -> None:
    """Persist the TS agent response into analysis_results and findings tables."""
    import uuid as _uuid
    from decimal import Decimal
    from sqlalchemy.orm import class_mapper
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisResult, Finding as FindingModel

    token_usage = result.get("tokenUsage", {})
    scores = result.get("scores", {})
    findings_data = result.get("findings", [])
    agent_breakdown = result.get("agentBreakdown")
    crossrun_summary = result.get("crossrunSummary")

    # Only pass JSONB columns accepted by the loaded ORM (avoids TypeError if worker
    # image lags migrations — see AnalysisResult.agent_breakdown / crossrun_summary).
    _cols = {c.key for c in class_mapper(AnalysisResult).columns}
    _optional = {}
    if "agent_breakdown" in _cols:
        _optional["agent_breakdown"] = agent_breakdown
    elif agent_breakdown is not None:
        log.warning(
            "analysis_result_orm_missing_column",
            column="agent_breakdown",
            hint="Redeploy worker/API so apps/api/models/analysis.py includes agent_breakdown",
        )
    if "crossrun_summary" in _cols:
        _optional["crossrun_summary"] = crossrun_summary
    elif crossrun_summary is not None:
        log.warning(
            "analysis_result_orm_missing_column",
            column="crossrun_summary",
            hint="Redeploy worker/API so apps/api/models/analysis.py includes crossrun_summary",
        )

    async with AsyncSessionFactory() as session:
        analysis_result = AnalysisResult(
            job_id=_uuid.UUID(job_id),
            tenant_id=_uuid.UUID(tenant_id),
            score_global=scores.get("global", 0),
            score_metrics=scores.get("metrics", 0),
            score_logs=scores.get("logs", 0),
            score_traces=scores.get("traces", 0),
            score_cost=scores.get("cost", 0),
            score_snr=scores.get("snr", 0),
            score_pipeline=scores.get("pipeline", 0),
            score_compliance=scores.get("compliance", 0),
            findings=findings_data,
            raw_llm_calls=token_usage.get("llmCalls", 0),
            input_tokens_total=token_usage.get("promptTokens", 0),
            output_tokens_total=token_usage.get("completionTokens", 0),
            cost_usd=Decimal(str(token_usage.get("costUsd", 0))),
            **_optional,
        )
        session.add(analysis_result)
        await session.flush()

        _finding_cols = {c.key for c in class_mapper(FindingModel).columns}

        for f in findings_data:
            _f_opt: dict = {}
            _f_extra = {
                "source_agent": f.get("sourceAgent"),
                "prompt_mode": f.get("promptMode"),
                "verified": f.get("verified", False),
                "confidence": f.get("confidence"),
                "reasoning_excerpt": f.get("reasoning"),
            }
            for k, v in _f_extra.items():
                if k in _finding_cols:
                    _f_opt[k] = v

            finding = FindingModel(
                result_id=analysis_result.id,
                tenant_id=_uuid.UUID(tenant_id),
                pillar=f.get("pillar", "traces"),
                severity=f.get("severity", "info"),
                dimension=f.get("dimension", "coverage"),
                title=f.get("title", ""),
                description=f.get("description", ""),
                file_path=f.get("filePath"),
                line_start=f.get("lineStart"),
                line_end=f.get("lineEnd"),
                suggestion=f.get("suggestion"),
                estimated_monthly_cost_impact=Decimal(str(f.get("estimatedMonthlyCostImpact", 0))),
                **_f_opt,
            )
            session.add(finding)

        await session.commit()


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
        await session.commit()


async def _clear_fix_pr_enqueue(job_id: str) -> None:
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob
    from sqlalchemy import select

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)))
        job = result.scalar_one_or_none()
        if job:
            job.fix_pr_enqueued_at = None
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


async def _publish_analysis_failed_redis(job_id: str, error_message: str) -> None:
    """Notify SSE subscribers that the analysis failed (worker catch path)."""
    from apps.agent.nodes.base import publish_analysis_event
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob
    from sqlalchemy import select

    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()
        if not job:
            return
        msg = (error_message or "Analysis failed.")[:2000]
        await publish_analysis_event(job_id, str(job.tenant_id), "failed", 0, msg)
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
