"""Analytics endpoints: overview, score-history, scores-by-tag, findings-by-tag, heatmap, cost-impact."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Float, Integer, and_, cast, distinct, extract, func, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_session_with_tenant
from apps.api.core.deps import CurrentUser
from apps.api.models.analysis import AnalysisJob, AnalysisResult, Finding
from apps.api.models.tag_system import AnalysisTag
from apps.api.services.tag_filter import parse_tag_filter as _parse_tag_filter, tag_filter_exists_clauses as _tag_filter_exists

log = structlog.get_logger(__name__)
router = APIRouter()


def _period_range(period: str) -> tuple[datetime, datetime, datetime, datetime]:
    """Return (start, end, prev_start, prev_end) for the given period string."""
    now = datetime.now(timezone.utc)
    days = {"30d": 30, "90d": 90, "180d": 180, "365d": 365}.get(period, 90)
    end = now
    start = now - timedelta(days=days)
    prev_end = start
    prev_start = prev_end - timedelta(days=days)
    return start, end, prev_start, prev_end


# ── Schemas ─────────────────────────────────────────────────────────────

class FindingsSummary(BaseModel):
    critical: int = 0
    warning: int = 0
    info: int = 0


class OverviewKPI(BaseModel):
    avg_score: float | None = None
    score_trend: float | None = None
    analyses_count: int = 0
    analyses_trend: float | None = None
    critical_findings: int = 0
    total_cost_impact: float = 0.0
    findings_summary: FindingsSummary = FindingsSummary()


class ScoreHistoryPoint(BaseModel):
    date: str
    global_score: float | None = None
    metrics: float | None = None
    logs: float | None = None
    traces: float | None = None
    group: str | None = None


class ScoresByTagGroup(BaseModel):
    tag_value: str
    avg_score: float | None = None
    trend: float | None = None
    analyses_count: int = 0
    repos_count: int = 0
    critical_findings: int = 0


class FindingsByTagGroup(BaseModel):
    tag_value: str
    critical: int = 0
    warning: int = 0
    info: int = 0
    top_titles: list[str] = []


class HeatmapCell(BaseModel):
    week: int
    dow: int
    count: int


class CostImpactData(BaseModel):
    total_monthly: float = 0.0
    by_pillar: dict[str, float] = {}
    top_findings: list[dict] = []


class AvailableTagKey(BaseModel):
    key: str
    count: int


# ── Endpoints ───────────────────────────────────────────────────────────

@router.get("/available-tag-keys", response_model=list[AvailableTagKey])
async def available_tag_keys(
    current: CurrentUser,
    period: str = Query("90d"),
) -> list[AvailableTagKey]:
    """
    Returns the distinct user-defined tag keys present in analysis_tags for
    completed analyses in the given period, ordered by frequency.
    System-generated keys (trigger, branch, type, pr, lang) are excluded.
    """
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    start, end, _, _ = _period_range(period)

    _SYSTEM_KEYS = {"trigger", "branch", "type", "pr", "lang"}

    async with get_session_with_tenant(tenant_id) as session:
        q = (
            select(
                AnalysisTag.key,
                func.count(AnalysisTag.id).label("cnt"),
            )
            .select_from(AnalysisTag)
            .join(AnalysisJob, AnalysisJob.id == AnalysisTag.job_id)
            .where(
                AnalysisTag.tenant_id == tid,
                AnalysisTag.source != "system",
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= start,
                AnalysisJob.completed_at <= end,
            )
            .group_by(AnalysisTag.key)
            .order_by(func.count(AnalysisTag.id).desc())
        )
        rows = (await session.execute(q)).all()

    return [
        AvailableTagKey(key=r.key, count=r.cnt)
        for r in rows
        if r.key not in _SYSTEM_KEYS
    ]


@router.get("/overview", response_model=OverviewKPI)
async def analytics_overview(
    current: CurrentUser,
    period: str = Query("90d"),
    tags: str | None = Query(None),
) -> OverviewKPI:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    start, end, prev_start, prev_end = _period_range(period)
    tag_pairs = _parse_tag_filter(tags)

    async with get_session_with_tenant(tenant_id) as session:
        base = (
            select(
                func.avg(AnalysisResult.score_global).label("avg_score"),
                func.count(AnalysisJob.id).label("cnt"),
            )
            .select_from(AnalysisJob)
            .join(AnalysisResult, AnalysisResult.job_id == AnalysisJob.id)
            .where(
                AnalysisJob.tenant_id == tid,
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= start,
                AnalysisJob.completed_at <= end,
            )
        )
        for clause in _tag_filter_exists(tag_pairs, tid):
            base = base.where(clause)
        row = (await session.execute(base)).one()
        avg_score = float(row.avg_score) if row.avg_score else None
        cnt = row.cnt or 0

        prev_q = (
            select(
                func.avg(AnalysisResult.score_global).label("avg_score"),
                func.count(AnalysisJob.id).label("cnt"),
            )
            .select_from(AnalysisJob)
            .join(AnalysisResult, AnalysisResult.job_id == AnalysisJob.id)
            .where(
                AnalysisJob.tenant_id == tid,
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= prev_start,
                AnalysisJob.completed_at <= prev_end,
            )
        )
        for clause in _tag_filter_exists(tag_pairs, tid):
            prev_q = prev_q.where(clause)
        prev_row = (await session.execute(prev_q)).one()
        prev_avg = float(prev_row.avg_score) if prev_row.avg_score else None
        prev_cnt = prev_row.cnt or 0

        score_trend = (avg_score - prev_avg) if (avg_score is not None and prev_avg is not None) else None
        analyses_trend = (cnt - prev_cnt) if prev_cnt else None

        sev_q = (
            select(
                func.sum(func.cast(Finding.severity == "critical", Integer)).label("crit"),
                func.sum(func.cast(Finding.severity == "warning", Integer)).label("warn"),
                func.sum(func.cast(Finding.severity == "info", Integer)).label("inf"),
            )
            .select_from(Finding)
            .join(AnalysisResult, AnalysisResult.id == Finding.result_id)
            .join(AnalysisJob, AnalysisJob.id == AnalysisResult.job_id)
            .where(
                Finding.tenant_id == tid,
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= start,
                AnalysisJob.completed_at <= end,
            )
        )
        for clause in _tag_filter_exists(tag_pairs, tid):
            sev_q = sev_q.where(clause)
        sev_row = (await session.execute(sev_q)).one()

        cost_q = (
            select(func.coalesce(func.sum(Finding.estimated_monthly_cost_impact), 0))
            .select_from(Finding)
            .join(AnalysisResult, AnalysisResult.id == Finding.result_id)
            .join(AnalysisJob, AnalysisJob.id == AnalysisResult.job_id)
            .where(
                Finding.tenant_id == tid,
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= start,
            )
        )
        for clause in _tag_filter_exists(tag_pairs, tid):
            cost_q = cost_q.where(clause)
        total_cost = float((await session.execute(cost_q)).scalar() or 0)

    return OverviewKPI(
        avg_score=round(avg_score, 1) if avg_score else None,
        score_trend=round(score_trend, 1) if score_trend is not None else None,
        analyses_count=cnt,
        analyses_trend=float(analyses_trend) if analyses_trend is not None else None,
        critical_findings=int(sev_row.crit or 0),
        total_cost_impact=round(total_cost, 2),
        findings_summary=FindingsSummary(
            critical=int(sev_row.crit or 0),
            warning=int(sev_row.warn or 0),
            info=int(sev_row.inf or 0),
        ),
    )


@router.get("/score-history", response_model=list[ScoreHistoryPoint])
async def score_history(
    current: CurrentUser,
    period: str = Query("90d"),
    granularity: str = Query("week"),
    tags: str | None = Query(None),
    group_by: str | None = Query(None, description="Optional: 'tag:<key>' to group by a tag key"),
) -> list[ScoreHistoryPoint]:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    start, end, _, _ = _period_range(period)
    tag_pairs = _parse_tag_filter(tags)

    trunc = "week" if granularity in ("week", "w") else "month" if granularity in ("month", "m") else "day"

    async with get_session_with_tenant(tenant_id) as session:
        date_col = func.date_trunc(trunc, AnalysisJob.completed_at).label("bucket")

        if group_by and group_by.startswith("tag:"):
            group_key = group_by[4:]
            q = (
                select(
                    date_col,
                    AnalysisTag.value.label("grp"),
                    func.avg(AnalysisResult.score_global).label("avg_global"),
                    func.avg(AnalysisResult.score_metrics).label("avg_metrics"),
                    func.avg(AnalysisResult.score_logs).label("avg_logs"),
                    func.avg(AnalysisResult.score_traces).label("avg_traces"),
                )
                .select_from(AnalysisJob)
                .join(AnalysisResult, AnalysisResult.job_id == AnalysisJob.id)
                .join(AnalysisTag, and_(AnalysisTag.job_id == AnalysisJob.id, AnalysisTag.key == group_key))
                .where(
                    AnalysisJob.tenant_id == tid,
                    AnalysisJob.status == "completed",
                    AnalysisJob.completed_at >= start,
                    AnalysisJob.completed_at <= end,
                )
                .group_by(date_col, AnalysisTag.value)
                .order_by(date_col)
            )
            for clause in _tag_filter_exists(tag_pairs, tid):
                q = q.where(clause)
            rows = (await session.execute(q)).all()
            return [
                ScoreHistoryPoint(
                    date=r.bucket.isoformat() if r.bucket else "",
                    global_score=round(float(r.avg_global), 1) if r.avg_global is not None else None,
                    metrics=round(float(r.avg_metrics), 1) if r.avg_metrics is not None else None,
                    logs=round(float(r.avg_logs), 1) if r.avg_logs is not None else None,
                    traces=round(float(r.avg_traces), 1) if r.avg_traces is not None else None,
                    group=r.grp,
                )
                for r in rows
            ]

        q = (
            select(
                date_col,
                func.avg(AnalysisResult.score_global).label("avg_global"),
                func.avg(AnalysisResult.score_metrics).label("avg_metrics"),
                func.avg(AnalysisResult.score_logs).label("avg_logs"),
                func.avg(AnalysisResult.score_traces).label("avg_traces"),
            )
            .select_from(AnalysisJob)
            .join(AnalysisResult, AnalysisResult.job_id == AnalysisJob.id)
            .where(
                AnalysisJob.tenant_id == tid,
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= start,
                AnalysisJob.completed_at <= end,
            )
            .group_by(date_col)
            .order_by(date_col)
        )
        for clause in _tag_filter_exists(tag_pairs, tid):
            q = q.where(clause)
        rows = (await session.execute(q)).all()

    return [
        ScoreHistoryPoint(
            date=r.bucket.isoformat() if r.bucket else "",
            global_score=round(float(r.avg_global), 1) if r.avg_global is not None else None,
            metrics=round(float(r.avg_metrics), 1) if r.avg_metrics is not None else None,
            logs=round(float(r.avg_logs), 1) if r.avg_logs is not None else None,
            traces=round(float(r.avg_traces), 1) if r.avg_traces is not None else None,
        )
        for r in rows
    ]


@router.get("/scores-by-tag", response_model=list[ScoresByTagGroup])
async def scores_by_tag(
    current: CurrentUser,
    key: str = Query(..., description="Tag key to group by (e.g. 'team')"),
    period: str = Query("90d"),
    tags: str | None = Query(None),
) -> list[ScoresByTagGroup]:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    start, end, prev_start, prev_end = _period_range(period)
    tag_pairs = _parse_tag_filter(tags)

    async with get_session_with_tenant(tenant_id) as session:
        q = (
            select(
                AnalysisTag.value.label("tv"),
                func.avg(AnalysisResult.score_global).label("avg"),
                func.count(AnalysisJob.id).label("cnt"),
                func.count(distinct(AnalysisJob.repo_id)).label("repos"),
            )
            .select_from(AnalysisJob)
            .join(AnalysisResult, AnalysisResult.job_id == AnalysisJob.id)
            .join(AnalysisTag, and_(AnalysisTag.job_id == AnalysisJob.id, AnalysisTag.key == key))
            .where(
                AnalysisJob.tenant_id == tid,
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= start,
                AnalysisJob.completed_at <= end,
            )
            .group_by(AnalysisTag.value)
            .order_by(func.avg(AnalysisResult.score_global).desc().nulls_last())
        )
        for clause in _tag_filter_exists(tag_pairs, tid):
            q = q.where(clause)
        rows = (await session.execute(q)).all()

    return [
        ScoresByTagGroup(
            tag_value=r.tv,
            avg_score=round(float(r.avg), 1) if r.avg else None,
            analyses_count=r.cnt,
            repos_count=r.repos,
        )
        for r in rows
    ]


@router.get("/findings-by-tag", response_model=list[FindingsByTagGroup])
async def findings_by_tag(
    current: CurrentUser,
    key: str = Query(..., description="Tag key to group by"),
    period: str = Query("90d"),
    tags: str | None = Query(None),
) -> list[FindingsByTagGroup]:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    start, end, _, _ = _period_range(period)
    tag_pairs = _parse_tag_filter(tags)

    async with get_session_with_tenant(tenant_id) as session:
        q = (
            select(
                AnalysisTag.value.label("tv"),
                func.sum(func.cast(Finding.severity == "critical", Integer)).label("c"),
                func.sum(func.cast(Finding.severity == "warning", Integer)).label("w"),
                func.sum(func.cast(Finding.severity == "info", Integer)).label("i"),
            )
            .select_from(Finding)
            .join(AnalysisResult, AnalysisResult.id == Finding.result_id)
            .join(AnalysisJob, AnalysisJob.id == AnalysisResult.job_id)
            .join(AnalysisTag, and_(AnalysisTag.job_id == AnalysisJob.id, AnalysisTag.key == key))
            .where(
                Finding.tenant_id == tid,
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= start,
                AnalysisJob.completed_at <= end,
            )
            .group_by(AnalysisTag.value)
            .order_by(func.sum(func.cast(Finding.severity == "critical", Integer)).desc().nulls_last())
        )
        for clause in _tag_filter_exists(tag_pairs, tid):
            q = q.where(clause)
        rows = (await session.execute(q)).all()

    return [
        FindingsByTagGroup(
            tag_value=r.tv,
            critical=int(r.c or 0),
            warning=int(r.w or 0),
            info=int(r.i or 0),
        )
        for r in rows
    ]


@router.get("/findings-by-pillar", response_model=list[FindingsByTagGroup])
async def findings_by_pillar(
    current: CurrentUser,
    period: str = Query("90d"),
    tags: str | None = Query(None),
) -> list[FindingsByTagGroup]:
    """Group findings by pillar (metrics, logs, traces, etc.)."""
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    start, end, _, _ = _period_range(period)
    tag_pairs = _parse_tag_filter(tags)

    async with get_session_with_tenant(tenant_id) as session:
        q = (
            select(
                Finding.pillar.label("tv"),
                func.sum(func.cast(Finding.severity == "critical", Integer)).label("c"),
                func.sum(func.cast(Finding.severity == "warning", Integer)).label("w"),
                func.sum(func.cast(Finding.severity == "info", Integer)).label("i"),
            )
            .select_from(Finding)
            .join(AnalysisResult, AnalysisResult.id == Finding.result_id)
            .join(AnalysisJob, AnalysisJob.id == AnalysisResult.job_id)
            .where(
                Finding.tenant_id == tid,
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= start,
                AnalysisJob.completed_at <= end,
            )
            .group_by(Finding.pillar)
            .order_by(func.sum(func.cast(Finding.severity == "critical", Integer)).desc().nulls_last())
        )
        for clause in _tag_filter_exists(tag_pairs, tid):
            q = q.where(clause)
        rows = (await session.execute(q)).all()

    return [
        FindingsByTagGroup(
            tag_value=r.tv or "unknown",
            critical=int(r.c or 0),
            warning=int(r.w or 0),
            info=int(r.i or 0),
        )
        for r in rows
    ]


@router.get("/heatmap", response_model=list[HeatmapCell])
async def activity_heatmap(
    current: CurrentUser,
    period: str = Query("90d"),
    tags: str | None = Query(None),
) -> list[HeatmapCell]:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    start, end, _, _ = _period_range(period)
    tag_pairs = _parse_tag_filter(tags)

    async with get_session_with_tenant(tenant_id) as session:
        week_col = func.extract("week", AnalysisJob.completed_at).label("wk")
        dow_col = func.extract("isodow", AnalysisJob.completed_at).label("dw")
        q = (
            select(week_col, dow_col, func.count(AnalysisJob.id).label("cnt"))
            .where(
                AnalysisJob.tenant_id == tid,
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= start,
                AnalysisJob.completed_at <= end,
            )
            .group_by(week_col, dow_col)
            .order_by(week_col, dow_col)
        )
        for clause in _tag_filter_exists(tag_pairs, tid):
            q = q.where(clause)
        rows = (await session.execute(q)).all()

    return [HeatmapCell(week=int(r.wk), dow=int(r.dw), count=r.cnt) for r in rows]


@router.get("/cost-impact", response_model=CostImpactData)
async def cost_impact(
    current: CurrentUser,
    period: str = Query("90d"),
    tags: str | None = Query(None),
) -> CostImpactData:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    start, end, _, _ = _period_range(period)
    tag_pairs = _parse_tag_filter(tags)

    async with get_session_with_tenant(tenant_id) as session:
        total_q = (
            select(func.coalesce(func.sum(Finding.estimated_monthly_cost_impact), 0).label("total"))
            .select_from(Finding)
            .join(AnalysisResult, AnalysisResult.id == Finding.result_id)
            .join(AnalysisJob, AnalysisJob.id == AnalysisResult.job_id)
            .where(
                Finding.tenant_id == tid,
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= start,
            )
        )
        for clause in _tag_filter_exists(tag_pairs, tid):
            total_q = total_q.where(clause)
        total = float((await session.execute(total_q)).scalar() or 0)

        by_pillar_q = (
            select(Finding.pillar, func.sum(Finding.estimated_monthly_cost_impact).label("s"))
            .select_from(Finding)
            .join(AnalysisResult, AnalysisResult.id == Finding.result_id)
            .join(AnalysisJob, AnalysisJob.id == AnalysisResult.job_id)
            .where(
                Finding.tenant_id == tid,
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= start,
            )
            .group_by(Finding.pillar)
        )
        for clause in _tag_filter_exists(tag_pairs, tid):
            by_pillar_q = by_pillar_q.where(clause)
        pillar_rows = (await session.execute(by_pillar_q)).all()
        by_pillar = {r.pillar: round(float(r.s or 0), 2) for r in pillar_rows}

        top_q = (
            select(Finding.title, func.sum(Finding.estimated_monthly_cost_impact).label("s"))
            .select_from(Finding)
            .join(AnalysisResult, AnalysisResult.id == Finding.result_id)
            .join(AnalysisJob, AnalysisJob.id == AnalysisResult.job_id)
            .where(
                Finding.tenant_id == tid,
                AnalysisJob.status == "completed",
                AnalysisJob.completed_at >= start,
                Finding.estimated_monthly_cost_impact > 0,
            )
            .group_by(Finding.title)
            .order_by(func.sum(Finding.estimated_monthly_cost_impact).desc())
            .limit(5)
        )
        for clause in _tag_filter_exists(tag_pairs, tid):
            top_q = top_q.where(clause)
        top_rows = (await session.execute(top_q)).all()
        top_findings = [{"title": r.title, "monthly_cost": round(float(r.s or 0), 2)} for r in top_rows]

    return CostImpactData(
        total_monthly=round(total, 2),
        by_pillar=by_pillar,
        top_findings=top_findings,
    )
