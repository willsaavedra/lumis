"""Analysis job creation and enqueueing logic."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.billing.billing_gate import ANALYSIS_COSTS, BillingGate
from apps.api.models.analysis import AnalysisJob
from apps.api.models.scm import Repository
from apps.api.services.tag_service import snapshot_tags_for_job

_CONTEXT_REFRESH_INTERVAL = timedelta(days=30)

log = structlog.get_logger(__name__)
billing_gate = BillingGate()


@dataclass
class AnalysisRequest:
    repo_full_name: str
    scm_repo_id: str
    scm_type: str
    commit_sha: str
    branch_ref: str
    pr_number: int | None
    changed_files: list[str]
    installation_id: str | None
    trigger: str


def infer_analysis_type(changed_files_count: int) -> str:
    if changed_files_count < 10:
        return "quick"
    return "full"


async def enqueue_analysis_from_webhook(
    session: AsyncSession,
    request: AnalysisRequest,
) -> AnalysisJob | None:
    """Process a webhook event and enqueue analysis if appropriate."""
    repo_result = await session.execute(
        select(Repository).where(
            Repository.scm_repo_id == request.scm_repo_id,
            Repository.is_active == True,
        )
    )
    repo = repo_result.scalar_one_or_none()
    if not repo:
        log.info("webhook_repo_not_active", scm_repo_id=request.scm_repo_id)
        return None

    tenant_id = str(repo.tenant_id)

    # Set tenant RLS context so that snapshot_tags_for_job can read repo_tags
    # (the webhook session is created without RLS — we scope it here once we know the tenant)
    await session.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))

    if request.commit_sha and request.pr_number:
        existing = await session.execute(
            select(AnalysisJob).where(
                AnalysisJob.repo_id == repo.id,
                AnalysisJob.commit_sha == request.commit_sha,
                AnalysisJob.pr_number == request.pr_number,
                AnalysisJob.status != "failed",
            )
        )
        if existing.scalar_one_or_none():
            log.info("webhook_duplicate_analysis", commit_sha=request.commit_sha[:8])
            return None

    analysis_type = infer_analysis_type(len(request.changed_files))
    scope_type = "selection" if analysis_type == "quick" else "full_repo"

    try:
        reservation_token, billing_snapshot = await billing_gate.check_and_reserve(
            tenant_id, analysis_type,
            scope_type=scope_type,
            files_count=len(request.changed_files),
        )
    except HTTPException as e:
        if e.status_code == 402:
            log.warning("webhook_insufficient_credits", tenant_id=tenant_id)
            return None
        raise

    job = AnalysisJob(
        tenant_id=uuid.UUID(tenant_id),
        repo_id=repo.id,
        status="pending",
        trigger=request.trigger,
        pr_number=request.pr_number,
        commit_sha=request.commit_sha,
        branch_ref=request.branch_ref,
        changed_files={"files": request.changed_files},
        analysis_type=analysis_type,
        scope_type=scope_type,
        credits_reserved=ANALYSIS_COSTS.get(analysis_type, 3),
        billing_reservation=billing_snapshot,
        selected_paths=request.changed_files[:500],
    )
    session.add(job)
    await session.flush()

    try:
        await snapshot_tags_for_job(
            session, tenant_id, job.id, repo.id,
            request.trigger, request.branch_ref, request.pr_number, analysis_type,
        )
    except Exception as e:
        log.warning("snapshot_tags_failed", job_id=str(job.id), error=str(e))

    from apps.worker.tasks import run_analysis
    run_analysis.delay(str(job.id), reservation_token)

    log.info(
        "analysis_enqueued",
        job_id=str(job.id),
        repo=request.repo_full_name,
        analysis_type=analysis_type,
        scope_type=scope_type,
    )
    return job


def _derive_analysis_type(changed_files: list[str] | None, has_context: bool) -> str:
    """Derive analysis type from scope when the caller does not specify one explicitly."""
    norm = [p.strip() for p in (changed_files or []) if p and str(p).strip()]
    if norm:
        return "quick"
    return "full" if has_context else "repository"


async def estimate_analysis_cost(
    session: AsyncSession,
    tenant_id: str,
    repo_id: str,
    paths: list[str],
    select_all: bool,
    *,
    scope_type: str | None = None,
    llm_provider: str | None = None,
    ref: str = "main",
) -> dict:
    """
    Return a cost estimate for a given scope selection.
    Includes both legacy credits and token-based USD estimates.
    """
    from apps.api.billing.billing_gate import (
        ANALYSIS_COSTS, USE_TOKEN_BILLING, estimate_cost as billing_estimate,
        PLAN_INCLUDED_REAL_COST,
    )
    from apps.api.models.auth import Tenant
    from apps.api.scm.scope_file_count import count_files_in_repo_scope

    repo_result = await session.execute(
        select(Repository)
        .where(
            Repository.id == uuid.UUID(repo_id),
            Repository.tenant_id == uuid.UUID(tenant_id),
            Repository.is_active == True,
        )
        .options(selectinload(Repository.connection))
    )
    repo = repo_result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found or not active.")

    has_context = bool(getattr(repo, "context_summary", None))

    if select_all or not paths:
        analysis_type = "full" if has_context else "repository"
        estimated_credits = ANALYSIS_COSTS.get(analysis_type, 3)
        file_count = 0
        path_count = 0
    else:
        norm_paths = [p.strip() for p in paths if p and str(p).strip()]
        path_count = len(norm_paths)
        analysis_type = "quick"
        resolved = await count_files_in_repo_scope(repo, repo.connection, ref, norm_paths)
        file_count = resolved if resolved is not None else path_count
        estimated_credits = min(15, max(1, 1 + file_count // 25))

    result: dict = {
        "file_count": file_count,
        "path_count": path_count,
        "estimated_credits": estimated_credits,
        "analysis_type": analysis_type,
    }

    if USE_TOKEN_BILLING:
        tenant_result = await session.execute(
            select(Tenant).where(Tenant.id == uuid.UUID(tenant_id))
        )
        tenant = tenant_result.scalar_one_or_none()
        plan = tenant.plan if tenant else "free"
        effective_provider = llm_provider or "cerebra_ai"

        effective_scope = scope_type or ("selection" if analysis_type == "quick" else "full_repo")

        # Check for prior analyses for cache estimation
        prior_count = await session.execute(
            select(AnalysisJob.id).where(
                AnalysisJob.repo_id == uuid.UUID(repo_id),
                AnalysisJob.status == "completed",
            ).limit(1)
        )
        has_prior = prior_count.scalar_one_or_none() is not None

        est = billing_estimate(
            max(1, file_count or 50),
            effective_scope,
            effective_provider,
            plan,
            has_prior,
        )

        included = PLAN_INCLUDED_REAL_COST.get(plan)
        used = float(tenant.real_cost_used_this_period or 0) if tenant else 0
        remaining = max(0, float(included or 0) - used) if included is not None else None

        result.update({
            "low_usd": est.low,
            "mid_usd": est.mid,
            "high_usd": est.high,
            "real_cost_mid_usd": est.real_cost_mid,
            "breakdown": est.breakdown,
            "budget_remaining_usd": remaining,
            "llm_provider": effective_provider,
        })

    return result


async def enqueue_manual_analysis(
    session: AsyncSession,
    tenant_id: str,
    repo_id: str,
    ref: str,
    analysis_type: str | None,
    *,
    changed_files: list[str] | None = None,
    llm_provider: str = "anthropic",
    scope_type: str | None = None,
    selected_paths: list[str] | None = None,
) -> AnalysisJob:
    """Enqueue a manual analysis triggered via API."""
    repo_result = await session.execute(
        select(Repository).where(
            Repository.id == uuid.UUID(repo_id),
            Repository.tenant_id == uuid.UUID(tenant_id),
            Repository.is_active == True,
        )
    )
    repo = repo_result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found or not active.")

    if not analysis_type:
        has_context = bool(getattr(repo, "context_summary", None))
        analysis_type = _derive_analysis_type(changed_files, has_context)

    # Derive scope_type from analysis_type if not provided
    if not scope_type:
        if analysis_type == "quick":
            scope_type = "selection"
        elif analysis_type == "context":
            scope_type = "context"
        else:
            scope_type = "full_repo"

    if analysis_type == "quick":
        norm = [p.strip() for p in (changed_files or []) if p and str(p).strip()]
        if not norm:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Quick analysis requires at least one file or directory path in changed_files.",
            )

    if analysis_type == "context":
        reservation_token = "context_free"
        billing_snapshot = None
    else:
        files_count = len(changed_files or selected_paths or [])
        reservation_token, billing_snapshot = await billing_gate.check_and_reserve(
            tenant_id, analysis_type,
            scope_type=scope_type,
            files_count=files_count,
            llm_provider=llm_provider,
        )

    files_payload: dict | None = None
    if changed_files:
        normalized = [p.strip().replace("\\", "/").lstrip("/") for p in changed_files if p and str(p).strip()]
        if normalized:
            files_payload = {"files": normalized[:500]}

    sel_paths = [p.strip().replace("\\", "/").lstrip("/") for p in (selected_paths or []) if p and str(p).strip()]

    job = AnalysisJob(
        tenant_id=uuid.UUID(tenant_id),
        repo_id=repo.id,
        status="pending",
        trigger="manual",
        branch_ref=ref,
        analysis_type=analysis_type,
        scope_type=scope_type,
        llm_provider=llm_provider,
        credits_reserved=ANALYSIS_COSTS.get(analysis_type, 3),
        changed_files=files_payload,
        selected_paths=sel_paths[:500] if sel_paths else [],
        billing_reservation=billing_snapshot,
    )
    session.add(job)
    await session.flush()

    try:
        await snapshot_tags_for_job(
            session, tenant_id, job.id, repo.id,
            "manual", ref, None, analysis_type,
        )
    except Exception as e:
        log.warning("snapshot_tags_failed", job_id=str(job.id), error=str(e))

    from apps.worker.tasks import run_analysis
    run_analysis.delay(str(job.id), reservation_token)

    if analysis_type in ("full", "repository"):
        await _maybe_enqueue_context_refresh(session, repo, tenant_id)

    return job


async def _maybe_enqueue_context_refresh(
    session: AsyncSession,
    repo: Repository,
    tenant_id: str,
) -> None:
    now = datetime.now(timezone.utc)
    context_updated_at = getattr(repo, "context_updated_at", None)

    needs_refresh = (
        repo.context_summary is None
        or context_updated_at is None
        or (now - context_updated_at) > _CONTEXT_REFRESH_INTERVAL
    )

    if not needs_refresh:
        return

    ctx_job = AnalysisJob(
        tenant_id=uuid.UUID(tenant_id),
        repo_id=repo.id,
        status="pending",
        trigger="scheduled",
        branch_ref=repo.default_branch,
        analysis_type="context",
        scope_type="context",
        credits_reserved=0,
    )
    session.add(ctx_job)
    await session.flush()

    from apps.worker.tasks import run_analysis
    run_analysis.delay(str(ctx_job.id), "context_free")

    log.info(
        "context_refresh_enqueued",
        repo_id=str(repo.id),
        context_updated_at=str(context_updated_at),
    )
