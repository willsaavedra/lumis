"""Analysis job creation and enqueueing logic."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.billing_gate import ANALYSIS_COSTS, BillingGate
from apps.api.models.analysis import AnalysisJob
from apps.api.models.scm import Repository

# Auto-enqueue a context refresh if the context summary is older than this
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
    # Find the repository in DB
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

    # Idempotency: check if this commit+PR already has an analysis
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

    try:
        reservation_token, billing_snapshot = await billing_gate.check_and_reserve(tenant_id, analysis_type)
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
        credits_reserved=ANALYSIS_COSTS.get(analysis_type, 3),
        billing_reservation=billing_snapshot,
    )
    session.add(job)
    await session.flush()

    # Enqueue Celery task
    from apps.worker.tasks import run_analysis
    run_analysis.delay(str(job.id), reservation_token)

    log.info(
        "analysis_enqueued",
        job_id=str(job.id),
        repo=request.repo_full_name,
        analysis_type=analysis_type,
    )
    return job


async def enqueue_manual_analysis(
    session: AsyncSession,
    tenant_id: str,
    repo_id: str,
    ref: str,
    analysis_type: str,
    *,
    changed_files: list[str] | None = None,
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

    if analysis_type == "quick":
        norm = [p.strip() for p in (changed_files or []) if p and str(p).strip()]
        if not norm:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Quick analysis requires at least one file or directory path in changed_files.",
            )

    # Context discovery is free — skip billing reservation
    if analysis_type == "context":
        reservation_token = "context_free"
        billing_snapshot = None
    else:
        reservation_token, billing_snapshot = await billing_gate.check_and_reserve(tenant_id, analysis_type)

    files_payload: dict | None = None
    if changed_files:
        normalized = [p.strip().replace("\\", "/").lstrip("/") for p in changed_files if p and str(p).strip()]
        if normalized:
            files_payload = {"files": normalized[:500]}

    job = AnalysisJob(
        tenant_id=uuid.UUID(tenant_id),
        repo_id=repo.id,
        status="pending",
        trigger="manual",
        branch_ref=ref,
        analysis_type=analysis_type,
        credits_reserved=ANALYSIS_COSTS.get(analysis_type, 3),
        changed_files=files_payload,
        billing_reservation=billing_snapshot,
    )
    session.add(job)
    await session.flush()

    from apps.worker.tasks import run_analysis
    run_analysis.delay(str(job.id), reservation_token)

    # Auto-enqueue context refresh if context_summary is missing or stale (>30 days old)
    if analysis_type in ("full", "repository"):
        await _maybe_enqueue_context_refresh(session, repo, tenant_id)

    return job


async def _maybe_enqueue_context_refresh(
    session: AsyncSession,
    repo: Repository,
    tenant_id: str,
) -> None:
    """
    If the repository context summary is missing or hasn't been refreshed in
    _CONTEXT_REFRESH_INTERVAL, silently enqueue a context analysis job.
    Context jobs are free (no credits), so no billing check is required.
    """
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
