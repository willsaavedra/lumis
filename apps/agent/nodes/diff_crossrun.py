"""Node: Compare current findings against the previous run for the same repo."""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from apps.agent.nodes.base import publish_progress, publish_thought
from apps.agent.nodes.deduplicate import _fingerprint
from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)


async def diff_crossrun_node(state: AgentState) -> dict:
    """
    For each finding in the current run, set `is_new` and `crossrun_status` by comparing
    fingerprints against the previous completed analysis for this repo.

    Computes resolved fingerprints (present before, absent now) for improvement UX.

    Also stores `previous_job_id` and `crossrun_summary` in state for persistence in post_report.
    """
    await publish_progress(state, "diffing", 74, "Comparing against previous run...", stage_index=7)

    findings: list[dict] = list(state.get("findings", []))
    request = state.get("request", {})
    repo_id = request.get("repo_id")
    job_id = state.get("job_id")

    previous_job_id: str | None = None
    prev_findings: list[dict] = []
    previous_score_global: int | None = None

    analysis_type = request.get("analysis_type")
    changed_files = list(request.get("changed_files") or [])

    if repo_id:
        try:
            previous_job_id, prev_findings, previous_score_global = await _load_previous_run_data(
                repo_id=repo_id,
                current_job_id=job_id,
                analysis_type=analysis_type,
                changed_files=changed_files,
            )
        except Exception as exc:
            span = trace.get_current_span()
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, str(exc))
            ctx = trace.get_current_span().get_span_context()
            log.warning("diff_crossrun_lookup_failed", trace_id=format(ctx.trace_id, "032x"), error=str(exc), exc_info=True)

    prev_fps: set[str] = set()
    fp_to_prev: dict[str, dict] = {}
    for pf in prev_findings:
        fp = _fingerprint(pf)
        prev_fps.add(fp)
        fp_to_prev[fp] = pf

    current_fps = {_fingerprint(f) for f in findings}
    resolved_fps = prev_fps - current_fps

    new_count = 0
    persisting_count = 0
    for finding in findings:
        fp = _fingerprint(finding)
        is_new = fp not in prev_fps
        finding["is_new"] = is_new
        finding["crossrun_status"] = "new" if is_new else "persisting"
        if is_new:
            new_count += 1
        else:
            persisting_count += 1

    resolved_items: list[dict[str, Any]] = []
    for fp in sorted(resolved_fps):
        pf = fp_to_prev.get(fp)
        if not pf:
            continue
        resolved_items.append({
            "fingerprint": fp,
            "pillar": pf.get("pillar"),
            "title": (pf.get("title") or "")[:500],
            "file_path": pf.get("file_path"),
            "line_start": pf.get("line_start"),
            "severity": pf.get("severity"),
        })

    resolved_count = len(resolved_items)

    current_score_global = state.get("scores", {}).get("global") if state.get("scores") else None

    crossrun_summary: dict[str, Any] = {
        "previous_job_id": previous_job_id,
        "previous_score_global": previous_score_global,
        "score_delta": (
            (current_score_global - previous_score_global)
            if current_score_global is not None and previous_score_global is not None
            else None
        ),
        "new_count": new_count,
        "persisting_count": persisting_count,
        "resolved_count": resolved_count,
        "resolved": resolved_items,
        "scope_aware": True,
        "compared_analysis_type": analysis_type,
    }

    log.info(
        "crossrun_diff_complete",
        total=len(findings),
        new=new_count,
        persisting=persisting_count,
        resolved=resolved_count,
        previous_job_id=previous_job_id,
        job_id=job_id,
    )
    await publish_thought(
        state, "diff_crossrun",
        f"{new_count} new, {persisting_count} persisting, {resolved_count} resolved vs. previous run",
        status="done",
    )
    await publish_progress(
        state, "diffing", 75,
        f"{new_count} new · {persisting_count} persisting · {resolved_count} resolved since last run.",
        stage_index=7,
    )
    return {
        "findings": findings,
        "previous_job_id": previous_job_id,
        "crossrun_summary": crossrun_summary,
    }


async def _load_previous_run_data(
    repo_id: str,
    current_job_id: str | None,
    analysis_type: str | None = None,
    changed_files: list[str] | None = None,
) -> tuple[str | None, list[dict], int | None]:
    """
    Latest completed AnalysisJob for this repo (excluding current), its findings
    JSON, and global score.

    Scope-aware: scoped (quick) runs match the most recent completed quick run
    with overlapping paths; full/repository runs match only other full/repository
    runs.  Falls back to same-analysis_type if no path overlap is found.
    """
    from sqlalchemy import select, and_

    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob, AnalysisResult

    base_conditions = [
        AnalysisJob.repo_id == uuid.UUID(repo_id),
        AnalysisJob.status == "completed",
    ]
    if current_job_id:
        base_conditions.append(AnalysisJob.id != uuid.UUID(current_job_id))

    async with AsyncSessionFactory() as session:
        prev_job = None

        if analysis_type == "quick" and changed_files:
            scope_set = set(changed_files)
            candidates_q = (
                select(AnalysisJob)
                .where(and_(*base_conditions, AnalysisJob.analysis_type == "quick"))
                .order_by(AnalysisJob.completed_at.desc())
                .limit(20)
            )
            cand_result = await session.execute(candidates_q)
            for cand in cand_result.scalars():
                cand_files = set(
                    (cand.changed_files or {}).get("files", [])
                    if isinstance(cand.changed_files, dict) else []
                )
                if cand_files & scope_set:
                    prev_job = cand
                    break

        if not prev_job and analysis_type:
            type_filter = (
                AnalysisJob.analysis_type.in_(["full", "repository"])
                if analysis_type in ("full", "repository")
                else AnalysisJob.analysis_type == analysis_type
            )
            q = (
                select(AnalysisJob)
                .where(and_(*base_conditions, type_filter))
                .order_by(AnalysisJob.completed_at.desc())
                .limit(1)
            )
            res = await session.execute(q)
            prev_job = res.scalar_one_or_none()

        if not prev_job:
            return None, [], None

        result_q = await session.execute(
            select(AnalysisResult).where(AnalysisResult.job_id == prev_job.id)
        )
        prev_result = result_q.scalar_one_or_none()

        if not prev_result or not prev_result.findings:
            return str(prev_job.id), [], prev_result.score_global if prev_result else None

        findings_list = prev_result.findings if isinstance(prev_result.findings, list) else []
        score = prev_result.score_global
        return str(prev_job.id), findings_list, score
