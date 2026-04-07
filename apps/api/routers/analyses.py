"""Analysis job endpoints."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import asc, desc, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.core.database import get_session_with_tenant
from apps.api.core.deps import CurrentUser
from apps.api.models.analysis import AnalysisJob, AnalysisResult, Finding, FindingFeedback, FEEDBACK_SIGNALS, FEEDBACK_TARGETS
from apps.api.models.scm import Repository
from apps.api.scm.repo_web_url import repo_web_url as build_repo_web_url

log = structlog.get_logger(__name__)
router = APIRouter()

# Fix PR: worker may take minutes — treat enqueue as "pending" for this long before allowing retry.
_FIX_PR_ENQUEUE_TTL = timedelta(hours=2)


def _fix_pr_enqueue_stale(enqueued_at: datetime | None) -> bool:
    """True if missing or older than TTL (safe to enqueue again)."""
    if enqueued_at is None:
        return True
    now = datetime.now(timezone.utc)
    at = enqueued_at if enqueued_at.tzinfo else enqueued_at.replace(tzinfo=timezone.utc)
    return now - at > _FIX_PR_ENQUEUE_TTL


def _fix_pr_pending(job: AnalysisJob) -> bool:
    if job.fix_pr_url:
        return False
    at = getattr(job, "fix_pr_enqueued_at", None)
    if at is None:
        return False
    return not _fix_pr_enqueue_stale(at)


def _is_valid_finding_id_value(val) -> bool:
    """True if val is a non-sentinel string that parses as a UUID (JSONB may store 'None' or null)."""
    if val is None:
        return False
    s = str(val).strip()
    if not s or s.lower() in ("none", "null", "undefined"):
        return False
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False


def _merge_finding_ids_from_orm(raw: list[dict], orm_rows: list[Finding] | None) -> list[dict]:
    """Use persisted Finding.id when the JSONB snapshot omits id or has a sentinel string."""
    if not raw:
        return []
    rows = list(orm_rows or [])
    out: list[dict] = []
    for i, d in enumerate(raw):
        merged = dict(d)
        oid = merged.get("id")
        if _is_valid_finding_id_value(oid):
            merged["id"] = str(oid).strip()
        elif i < len(rows):
            merged["id"] = str(rows[i].id)
        elif oid is not None:
            merged["id"] = str(oid)
        out.append(merged)
    return out


def _parse_uuid_param(value: str, *, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value.strip())
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field}",
        )


class TriggerAnalysisRequest(BaseModel):
    repo_id: str
    ref: str = "main"
    analysis_type: str | None = Field(
        default=None,
        description=(
            "If omitted the server derives the type: specific changed_files → quick; "
            "no paths + context exists → full; no paths + no context → repository."
        ),
    )
    llm_provider: Literal["anthropic", "cerebra_ai"] = "cerebra_ai"
    changed_files: list[str] | None = Field(
        default=None,
        description="Paths relative to repo root (files or dirs). Required for quick; optional for full/repository.",
    )


class EstimateRequest(BaseModel):
    repo_id: str
    paths: list[str] | None = Field(default=None, description="Selected file/folder paths. Null or empty means select-all.")
    select_all: bool = False
    ref: str = "main"


class EstimateResponse(BaseModel):
    file_count: int
    estimated_credits: int
    analysis_type: str


class AnalysisResultPayload(BaseModel):
    """Scores + findings for dashboard detail view."""

    score_global: int | None = None
    score_metrics: int | None = None
    score_logs: int | None = None
    score_traces: int | None = None
    findings: list[dict] = Field(default_factory=list)
    crossrun_summary: dict | None = None
    # Execution telemetry
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    cost_usd: float = 0.0


class AnalysisJobResponse(BaseModel):
    id: str
    repo_id: str
    repo_full_name: str | None = None
    repo_web_url: str | None = None
    scm_type: str = "github"
    status: str
    trigger: str
    analysis_type: str
    llm_provider: str = "anthropic"
    branch_ref: str | None = None
    pr_number: int | None
    commit_sha: str | None
    credits_consumed: int | None
    score_global: int | None
    created_at: str
    started_at: str | None = None
    completed_at: str | None
    fix_pr_url: str | None = None
    fix_pr_pending: bool = False
    fix_pr_eligible: bool = False
    scope_paths: list[str] | None = None
    result: AnalysisResultPayload | None = None


class AnalysisListResponse(BaseModel):
    items: list[AnalysisJobResponse]
    total: int


_SORTABLE = frozenset(
    {"created_at", "completed_at", "status", "score_global", "credits_consumed", "analysis_type", "trigger", "repo"}
)


@router.post("/estimate", response_model=EstimateResponse)
async def estimate_analysis(body: EstimateRequest, current: CurrentUser) -> EstimateResponse:
    """Return a lightweight credit/type estimate without starting an analysis."""
    user, tenant_id, _ = current
    from apps.api.services.analysis_service import estimate_analysis_cost
    async with get_session_with_tenant(tenant_id) as session:
        result = await estimate_analysis_cost(
            session,
            tenant_id,
            body.repo_id,
            paths=body.paths or [],
            select_all=body.select_all,
        )
    return EstimateResponse(**result)


@router.post("", response_model=AnalysisJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_analysis(body: TriggerAnalysisRequest, current: CurrentUser) -> AnalysisJobResponse:
    user, tenant_id, _ = current
    from apps.api.services.analysis_service import enqueue_manual_analysis
    async with get_session_with_tenant(tenant_id) as session:
        job = await enqueue_manual_analysis(
            session,
            tenant_id,
            body.repo_id,
            body.ref,
            body.analysis_type,
            changed_files=body.changed_files,
            llm_provider=body.llm_provider,
        )
        loaded = await session.execute(
            select(AnalysisJob)
            .where(AnalysisJob.id == job.id)
            .options(
                selectinload(AnalysisJob.repository).selectinload(Repository.connection),
                selectinload(AnalysisJob.result).selectinload(AnalysisResult.findings_list),
            )
        )
        job = loaded.scalar_one()
    return _job_to_response(job)


@router.post("/{job_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_analysis(job_id: str, current: CurrentUser) -> dict:
    """Cancel a running or pending analysis."""
    user, tenant_id, _ = current
    import redis.asyncio as aioredis
    from apps.api.core.config import settings as app_settings

    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(AnalysisJob).where(
                AnalysisJob.id == uuid.UUID(job_id),
                AnalysisJob.tenant_id == uuid.UUID(tenant_id),
            )
        )
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Analysis not found")
        if job.status not in ("pending", "running"):
            raise HTTPException(status_code=409, detail=f"Cannot cancel analysis in '{job.status}' state")

        job.status = "failed"
        job.error_message = "Cancelled by user"
        job.completed_at = datetime.now(timezone.utc)

    # Publish SSE error event so the live page reacts immediately
    try:
        event_obj = json.dumps({
            "event_type": "error",
            "message": "Analysis cancelled by user",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False)
        channel = f"t:{tenant_id}:analysis:{job_id}:progress"
        timeline_key = f"t:{tenant_id}:analysis:{job_id}:timeline"
        r = aioredis.from_url(app_settings.redis_url, decode_responses=True)
        try:
            await r.publish(channel, f"event: error\ndata: {event_obj}\n\n")
            await r.rpush(timeline_key, event_obj)
            await r.expire(timeline_key, 604800)
        finally:
            await r.aclose()
    except Exception as exc:
        log.warning("cancel_publish_failed", job_id=job_id, error=str(exc))

    log.info("analysis_cancelled", job_id=job_id, user=str(user.id))
    return {"status": "cancelled", "job_id": job_id}


def _apply_analysis_list_filters(
    tenant_id: str,
    *,
    status: str | None,
    trigger: str | None,
    analysis_type: str | None,
    repo_id: str | None,
    q: str | None,
    fix_pr: str | None,
) -> tuple[list, bool]:
    """Build shared WHERE fragments for list + count. Returns (conditions, need_repo_join)."""
    tenant_uuid = uuid.UUID(tenant_id)
    stale_cutoff = datetime.now(timezone.utc) - _FIX_PR_ENQUEUE_TTL
    conditions: list = [
        AnalysisJob.tenant_id == tenant_uuid,
        AnalysisJob.analysis_type != "context",
    ]
    need_repo_join = False

    if status:
        allowed_s = {"pending", "running", "completed", "failed"}
        parts = [s.strip() for s in status.split(",") if s.strip() in allowed_s]
        if parts:
            conditions.append(AnalysisJob.status.in_(parts))
    if trigger:
        conditions.append(AnalysisJob.trigger == trigger)
    if analysis_type:
        conditions.append(AnalysisJob.analysis_type == analysis_type)
    if repo_id:
        try:
            conditions.append(AnalysisJob.repo_id == uuid.UUID(repo_id))
        except ValueError as e:
            raise HTTPException(status_code=400, detail="Invalid repo_id.") from e
    if q and q.strip():
        need_repo_join = True
        conditions.append(Repository.full_name.ilike(f"%{q.strip()}%"))

    if fix_pr == "has_pr":
        conditions.append(AnalysisJob.fix_pr_url.isnot(None))
    elif fix_pr == "generating":
        conditions.append(AnalysisJob.fix_pr_url.is_(None))
        conditions.append(AnalysisJob.fix_pr_enqueued_at.isnot(None))
        conditions.append(AnalysisJob.fix_pr_enqueued_at >= stale_cutoff)
    elif fix_pr == "can_suggest":
        conditions.append(AnalysisJob.status == "completed")
        conditions.append(AnalysisJob.fix_pr_url.is_(None))
        conditions.append(
            or_(
                AnalysisJob.fix_pr_enqueued_at.is_(None),
                AnalysisJob.fix_pr_enqueued_at < stale_cutoff,
            )
        )
        actionable_exists = exists(
            select(1)
            .select_from(Finding)
            .join(AnalysisResult, Finding.result_id == AnalysisResult.id)
            .where(
                AnalysisResult.job_id == AnalysisJob.id,
                Finding.file_path.isnot(None),
                Finding.severity.in_(["critical", "warning"]),
                Finding.pillar.in_(["metrics", "logs", "traces"]),
            )
        )
        conditions.append(actionable_exists)

    return conditions, need_repo_join


@router.get("", response_model=AnalysisListResponse)
async def list_analyses(
    current: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: str = Query("created_at"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    status: str | None = Query(None, description="Comma-separated: pending,running,completed,failed"),
    trigger: str | None = Query(None),
    analysis_type: str | None = Query(None),
    repo_id: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    fix_pr: str | None = Query(None),
) -> AnalysisListResponse:
    user, tenant_id, _ = current
    if sort not in _SORTABLE:
        sort = "created_at"
    if fix_pr is not None and fix_pr not in ("has_pr", "generating", "can_suggest"):
        raise HTTPException(status_code=400, detail="fix_pr must be has_pr, generating, or can_suggest.")

    conditions, need_repo_join = _apply_analysis_list_filters(
        tenant_id,
        status=status,
        trigger=trigger,
        analysis_type=analysis_type,
        repo_id=repo_id,
        q=q,
        fix_pr=fix_pr,
    )
    if sort == "repo":
        need_repo_join = True

    def _base_select_from():
        f = select(AnalysisJob).where(*conditions)
        f = f.outerjoin(AnalysisResult, AnalysisResult.job_id == AnalysisJob.id)
        if need_repo_join:
            f = f.join(Repository, AnalysisJob.repo_id == Repository.id)
        return f

    count_stmt = select(func.count(func.distinct(AnalysisJob.id))).select_from(AnalysisJob).where(*conditions)
    count_stmt = count_stmt.outerjoin(AnalysisResult, AnalysisResult.job_id == AnalysisJob.id)
    if need_repo_join:
        count_stmt = count_stmt.join(Repository, AnalysisJob.repo_id == Repository.id)

    sort_col_map = {
        "created_at": AnalysisJob.created_at,
        "completed_at": AnalysisJob.completed_at,
        "status": AnalysisJob.status,
        "score_global": AnalysisResult.score_global,
        "credits_consumed": AnalysisJob.credits_consumed,
        "analysis_type": AnalysisJob.analysis_type,
        "trigger": AnalysisJob.trigger,
        "repo": Repository.full_name,
    }
    sort_expr = sort_col_map[sort]
    if order == "desc":
        order_by = desc(sort_expr).nulls_last()
    else:
        order_by = asc(sort_expr).nulls_last()

    list_stmt = _base_select_from().options(
        selectinload(AnalysisJob.result).selectinload(AnalysisResult.findings_list),
        selectinload(AnalysisJob.repository).selectinload(Repository.connection),
    )
    list_stmt = list_stmt.order_by(order_by, desc(AnalysisJob.created_at)).limit(limit).offset(offset)

    async with get_session_with_tenant(tenant_id) as session:
        total = (await session.execute(count_stmt)).scalar_one()
        result = await session.execute(list_stmt)
        jobs = result.scalars().unique().all()

    return AnalysisListResponse(items=[_job_to_response(j) for j in jobs], total=int(total))


@router.get("/{job_id}", response_model=AnalysisJobResponse)
async def get_analysis(job_id: str, current: CurrentUser) -> AnalysisJobResponse:
    user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(AnalysisJob)
            .where(AnalysisJob.id == uuid.UUID(job_id))
            .options(
                selectinload(AnalysisJob.result).selectinload(AnalysisResult.findings_list),
                selectinload(AnalysisJob.repository).selectinload(Repository.connection),
            )
        )
        job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return _job_to_response(job)


@router.post("/{job_id}/fix-pr", status_code=status.HTTP_202_ACCEPTED)
async def create_fix_pr(job_id: str, current: CurrentUser) -> dict:
    """Enqueue a task to generate code fixes and open a GitHub PR."""
    user, tenant_id, _ = current
    from apps.api.services.fix_pr_service import has_recommendations_for_fix_pr
    from apps.worker.tasks import create_fix_pr as _task

    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(AnalysisJob)
            .where(AnalysisJob.id == uuid.UUID(job_id), AnalysisJob.tenant_id == uuid.UUID(tenant_id))
            .options(
                selectinload(AnalysisJob.result).selectinload(AnalysisResult.findings_list),
            )
        )
        job = result.scalar_one_or_none()

        if not job:
            raise HTTPException(status_code=404, detail="Analysis not found.")
        if job.status != "completed":
            raise HTTPException(status_code=400, detail="Analysis must be completed before creating a fix PR.")
        if job.fix_pr_url:
            return {"status": "already_created", "pr_url": job.fix_pr_url}
        if not has_recommendations_for_fix_pr(job):
            raise HTTPException(
                status_code=400,
                detail="No actionable recommendations with file paths to include in a fix PR.",
            )

        if job.fix_pr_enqueued_at is not None:
            if not _fix_pr_enqueue_stale(job.fix_pr_enqueued_at):
                return {"status": "processing", "job_id": job_id}
            job.fix_pr_enqueued_at = None

        job.fix_pr_enqueued_at = datetime.now(timezone.utc)
        await session.commit()

    _task.delay(job_id)
    return {"status": "enqueued", "job_id": job_id}


def _timeline_key(tenant_id: str, job_id: str) -> str:
    return f"t:{tenant_id}:analysis:{job_id}:timeline"


@router.get("/{job_id}/stream")
async def stream_analysis_progress(job_id: str, current: CurrentUser) -> StreamingResponse:
    """SSE endpoint: Redis timeline replay (survives refresh) then live pub/sub."""
    user, tenant_id, _ = current

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")

    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(AnalysisJob).where(
                AnalysisJob.id == job_uuid,
                AnalysisJob.tenant_id == uuid.UUID(tenant_id),
            )
        )
        job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")

    ts = datetime.now(timezone.utc).isoformat()
    tk = _timeline_key(tenant_id, job_id)

    async def replay_then_live(
        *,
        terminal_fallback: dict | None = None,
    ) -> AsyncGenerator[str, None]:
        from apps.api.core.redis_client import get_redis

        def _sse_frame(raw_json: str) -> str:
            """Build SSE frame with event type prefix when available."""
            try:
                obj = json.loads(raw_json)
                etype = obj.get("event_type", "progress")
            except Exception:
                etype = "progress"
            return f"event: {etype}\ndata: {raw_json}\n\n"

        redis = get_redis()
        channel = f"t:{tenant_id}:analysis:{job_id}:progress"
        try:
            history = await redis.lrange(tk, 0, -1)
            terminal_seen = False
            for raw in history:
                yield _sse_frame(raw)
                try:
                    ev = json.loads(raw)
                    if ev.get("stage") in ("done", "failed") or ev.get("event_type") == "done":
                        terminal_seen = True
                except Exception:
                    pass

            if terminal_seen:
                return

            if terminal_fallback and not history:
                yield _sse_frame(json.dumps(terminal_fallback))
                return

            pubsub = redis.pubsub()
            await pubsub.subscribe(channel)
            try:
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and message.get("data") is not None:
                        raw = message["data"]
                        data = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                        yield _sse_frame(data)
                        try:
                            parsed = json.loads(data)
                            if parsed.get("stage") in ("done", "failed") or parsed.get("event_type") == "done":
                                break
                        except Exception:
                            pass
                    await asyncio.sleep(0.1)
            finally:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
        finally:
            await redis.aclose()

    if job.status == "completed":
        fallback = {
            "event_type": "done",
            "stage": "done",
            "progress_pct": 100,
            "message": "Analysis complete.",
            "timestamp": ts,
            "analysis_id": job_id,
            "score_global": job.result.score_global if hasattr(job, "result") and job.result else 0,
            "redirect_to": f"/analyses/{job_id}",
        }
        return StreamingResponse(
            replay_then_live(terminal_fallback=fallback),
            media_type="text/event-stream",
        )

    if job.status == "failed":
        fallback = {
            "event_type": "error",
            "stage": "failed",
            "progress_pct": 0,
            "message": (job.error_message or "Analysis failed.")[:2000],
            "timestamp": ts,
        }
        return StreamingResponse(
            replay_then_live(terminal_fallback=fallback),
            media_type="text/event-stream",
        )

    return StreamingResponse(replay_then_live(), media_type="text/event-stream")


def _job_to_response(job: AnalysisJob) -> AnalysisJobResponse:
    from apps.api.services.fix_pr_service import has_recommendations_for_fix_pr

    score = None
    result_payload: AnalysisResultPayload | None = None
    try:
        if job.result:
            r = job.result
            score = r.score_global
            raw_findings = r.findings
            if isinstance(raw_findings, list):
                orm_rows = getattr(r, "findings_list", None) or []
                findings_list = _merge_finding_ids_from_orm(raw_findings, orm_rows)
            else:
                findings_list = []
            result_payload = AnalysisResultPayload(
                score_global=r.score_global,
                score_metrics=r.score_metrics,
                score_logs=r.score_logs,
                score_traces=r.score_traces,
                findings=findings_list,
                crossrun_summary=r.crossrun_summary if isinstance(getattr(r, "crossrun_summary", None), dict) else None,
                input_tokens=getattr(r, "input_tokens_total", 0) or 0,
                output_tokens=getattr(r, "output_tokens_total", 0) or 0,
                llm_calls=getattr(r, "raw_llm_calls", 0) or 0,
                cost_usd=float(getattr(r, "cost_usd", 0) or 0),
            )
    except Exception:
        pass
    repo_full_name = None
    repo_web_url_val = None
    scm_type = "github"
    try:
        if job.repository:
            repo_full_name = job.repository.full_name
            conn = job.repository.connection
            if conn is not None and conn.scm_type:
                scm_type = conn.scm_type
            repo_web_url_val = build_repo_web_url(
                scm_type=scm_type,
                full_name=job.repository.full_name,
                clone_url=getattr(job.repository, "clone_url", None),
            )
    except Exception:
        pass
    scope_paths: list[str] | None = None
    if job.changed_files and isinstance(job.changed_files, dict):
        files = job.changed_files.get("files")
        if files and isinstance(files, list) and len(files) > 0:
            scope_paths = files

    return AnalysisJobResponse(
        id=str(job.id),
        repo_id=str(job.repo_id),
        repo_full_name=repo_full_name,
        repo_web_url=repo_web_url_val,
        scm_type=scm_type,
        status=job.status,
        trigger=job.trigger,
        analysis_type=job.analysis_type,
        llm_provider=getattr(job, "llm_provider", None) or "anthropic",
        branch_ref=job.branch_ref,
        pr_number=job.pr_number,
        commit_sha=job.commit_sha,
        credits_consumed=job.credits_consumed,
        score_global=score,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        fix_pr_url=job.fix_pr_url,
        fix_pr_pending=_fix_pr_pending(job),
        fix_pr_eligible=has_recommendations_for_fix_pr(job),
        scope_paths=scope_paths,
        result=result_payload,
    )


# ---------------------------------------------------------------------------
# Feedback endpoints
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    signal: str
    target_type: str = "finding"
    note: str | None = None


class FeedbackResponse(BaseModel):
    id: str
    finding_id: str
    target_type: str
    signal: str
    feedback_at: str


@router.post(
    "/{job_id}/findings/{finding_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit feedback signal for a finding (thumbs up/down/ignored/applied)",
)
async def submit_finding_feedback(
    job_id: str,
    finding_id: str,
    body: FeedbackRequest,
    current: CurrentUser,
) -> FeedbackResponse:
    """
    Record a user feedback signal against a specific finding.

    Signals:
      thumbs_up   → finding is correct, useful
      thumbs_down → finding is a false positive
      ignored     → user acknowledged but chose to ignore
      applied     → user applied the suggestion (confirmed TP)

    Powers the tuning flywheel: thumbs_down events are exported as
    false-positive eval cases via scripts/import_feedback.py.
    """
    if body.signal not in FEEDBACK_SIGNALS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"signal must be one of: {', '.join(FEEDBACK_SIGNALS)}",
        )
    if body.target_type not in FEEDBACK_TARGETS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"target_type must be one of: {', '.join(FEEDBACK_TARGETS)}",
        )

    user, tenant_id, _ = current
    fid = _parse_uuid_param(finding_id, field="finding_id")
    jid = _parse_uuid_param(job_id, field="job_id")
    async with get_session_with_tenant(tenant_id) as session:
        # Verify the finding belongs to this tenant's job
        finding_check = await session.execute(
            select(Finding)
            .join(AnalysisResult, Finding.result_id == AnalysisResult.id)
            .join(AnalysisJob, AnalysisResult.job_id == AnalysisJob.id)
            .where(
                Finding.id == fid,
                AnalysisJob.id == jid,
                AnalysisJob.tenant_id == uuid.UUID(tenant_id),
            )
        )
        finding = finding_check.scalar_one_or_none()
        if not finding:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")

        fb = FindingFeedback(
            finding_id=fid,
            job_id=jid,
            tenant_id=uuid.UUID(tenant_id),
            target_type=body.target_type,
            signal=body.signal,
            note=body.note,
        )
        session.add(fb)
        await session.commit()
        await session.refresh(fb)

    log.info(
        "finding_feedback_recorded",
        finding_id=finding_id,
        job_id=job_id,
        target_type=body.target_type,
        signal=body.signal,
        tenant_id=tenant_id,
    )

    return FeedbackResponse(
        id=str(fb.id),
        finding_id=str(fid),
        target_type=fb.target_type,
        signal=body.signal,
        feedback_at=fb.feedback_at.isoformat(),
    )


@router.get(
    "/{job_id}/findings/{finding_id}/feedback",
    response_model=list[FeedbackResponse],
    summary="Get all feedback signals for a finding",
)
async def get_finding_feedback(
    job_id: str,
    finding_id: str,
    current: CurrentUser,
) -> list[FeedbackResponse]:
    user, tenant_id, _ = current
    fid = _parse_uuid_param(finding_id, field="finding_id")
    jid = _parse_uuid_param(job_id, field="job_id")
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(FindingFeedback)
            .where(
                FindingFeedback.finding_id == fid,
                FindingFeedback.job_id == jid,
                FindingFeedback.tenant_id == uuid.UUID(tenant_id),
            )
            .order_by(FindingFeedback.feedback_at.desc())
        )
        feedbacks = result.scalars().all()

    return [
        FeedbackResponse(
            id=str(fb.id),
            finding_id=str(fb.finding_id),
            target_type=fb.target_type,
            signal=fb.signal,
            feedback_at=fb.feedback_at.isoformat(),
        )
        for fb in feedbacks
    ]
