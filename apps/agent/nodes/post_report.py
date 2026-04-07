"""Node 9: Save results to DB, consume billing, publish execution summary, post PR comment."""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone

import structlog

from apps.agent.nodes.base import (
    publish_analysis_event,
    publish_progress,
    publish_thought,
    publish_cost_update,
    publish_done,
)
from apps.agent.nodes.finding_snippets import enrich_findings_code_snippets
from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)


def build_execution_summary(state: AgentState) -> dict:
    """Assemble full execution receipt from agent state token_usage."""
    usage = state.get("token_usage") or {}
    scores = state.get("efficiency_scores", {})
    findings = state.get("findings", [])
    by_node = usage.get("by_node", {})
    provider = state.get("request", {}).get("llm_provider", "anthropic")
    manifest = state.get("analysis_manifest")

    summary = {
        "token_breakdown": {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cached_tokens": usage.get("cached_tokens", 0),
            "llm_calls": usage.get("llm_calls", 0),
            "by_node": by_node,
        },
        "cost_breakdown": {
            "llm_cost_usd": usage.get("cost_usd", 0.0),
            "llm_provider": provider,
        },
        "findings_summary": {
            "total": len(findings),
            "critical": sum(1 for f in findings if f.get("severity") == "critical"),
            "warning": sum(1 for f in findings if f.get("severity") == "warning"),
            "info": sum(1 for f in findings if f.get("severity") == "info"),
        },
        "scores": {
            "global": scores.get("global_score"),
            "metrics": scores.get("metrics"),
            "logs": scores.get("logs"),
            "traces": scores.get("traces"),
        },
    }

    if manifest:
        summary["completeness"] = manifest

    return summary


async def post_report_node(state: AgentState) -> dict:
    """Save analysis results to DB and post PR comment."""
    await publish_progress(state, "posting", 90, "Saving results...", stage_index=9)

    job_id = state["job_id"]
    tenant_id = state["tenant_id"]
    findings = state.get("findings", [])
    scores = state.get("efficiency_scores", {})
    token_usage = state.get("token_usage", {})

    previous_job_id = state.get("previous_job_id")
    crossrun_summary = state.get("crossrun_summary")

    enrich_findings_code_snippets(findings, state)

    # Build execution summary
    exec_summary = build_execution_summary(state)

    # Consume billing with real token counts
    cost_breakdown: dict = {}
    try:
        from apps.api.billing.billing_gate import BillingGate
        billing = BillingGate()

        request = state.get("request", {})
        reservation_token = request.get("reservation_token") or request.get("billing_token") or ""
        provider = request.get("llm_provider", "anthropic")

        files_analyzed = len([f for f in (state.get("changed_files") or []) if isinstance(f, dict)])

        if reservation_token:
            cost_breakdown = await billing.consume(
                reservation_token=reservation_token,
                job_id=job_id,
                tenant_id=tenant_id,
                total_input_tokens=token_usage.get("input_tokens", 0),
                total_output_tokens=token_usage.get("output_tokens", 0),
                total_cached_tokens=token_usage.get("cached_tokens", 0),
                files_analyzed=files_analyzed,
                rag_chunks_retrieved=0,
                llm_provider=provider,
            )
    except Exception as billing_err:
        log.error("billing_consume_failed", job_id=job_id, error=str(billing_err))

    if cost_breakdown:
        exec_summary["cost_breakdown"] = cost_breakdown

    try:
        await _save_to_db(
            job_id, tenant_id, findings, scores, token_usage,
            previous_job_id, crossrun_summary, cost_breakdown=cost_breakdown,
        )
    except Exception as e:
        log.error("save_to_db_failed", job_id=job_id, error=str(e))

    # Post to SCM if PR analysis
    request = state.get("request", {})
    pr_number = request.get("pr_number")
    if pr_number:
        try:
            await _post_pr_comment(request, findings, scores)
        except Exception as e:
            log.warning("post_pr_comment_failed", error=str(e))

    # Cleanup cloned repo
    if state.get("repo_path"):
        shutil.rmtree(state["repo_path"], ignore_errors=True)
        log.info("repo_cleaned_up", path=state["repo_path"])

    score_global = scores.get("global_score")

    # Publish execution_summary SSE event before done
    # stage must NOT be "done"/"failed" — those are terminal signals that close the SSE stream
    await publish_analysis_event(
        job_id, tenant_id, "summary", 99,
        "Execution summary ready",
        event_type="execution_summary",
        extra=exec_summary,
    )

    await publish_thought(
        state, "post_report",
        f"Results saved — {len(findings)} findings, global score {score_global}/100",
        status="done",
    )
    await publish_cost_update(state, node="post_report")
    await publish_done(state, score_global=score_global)
    return {"stage": "done", "progress_pct": 100}


async def _save_to_db(
    job_id: str,
    tenant_id: str,
    findings: list[dict],
    scores: dict,
    token_usage: dict,
    previous_job_id: str | None = None,
    crossrun_summary: dict | None = None,
    cost_breakdown: dict | None = None,
) -> None:
    from sqlalchemy import select

    from apps.api.core.database import get_session_with_tenant
    from apps.api.models.analysis import AnalysisJob, AnalysisResult, Finding

    async with get_session_with_tenant(tenant_id) as session:
        job_result = await session.execute(
            select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id))
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return

        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        if not job.credits_consumed:
            job.credits_consumed = job.credits_reserved

        summary_db: dict | None = None
        if crossrun_summary:
            summary_db = dict(crossrun_summary)
            cur = scores.get("global_score")
            prev = summary_db.get("previous_score_global")
            if prev is not None and cur is not None:
                summary_db["score_delta"] = int(cur) - int(prev)

        result = AnalysisResult(
            job_id=uuid.UUID(job_id),
            tenant_id=uuid.UUID(tenant_id),
            previous_job_id=uuid.UUID(previous_job_id) if previous_job_id else None,
            crossrun_summary=summary_db,
            score_global=scores.get("global_score"),
            score_metrics=scores.get("metrics"),
            score_logs=scores.get("logs"),
            score_traces=scores.get("traces"),
            score_cost=scores.get("cost"),
            score_snr=scores.get("snr"),
            score_pipeline=scores.get("pipeline"),
            score_compliance=scores.get("compliance"),
            findings=findings,
            raw_llm_calls=token_usage.get("llm_calls", 0),
            input_tokens_total=token_usage.get("input_tokens", 0),
            output_tokens_total=token_usage.get("output_tokens", 0),
            cost_usd=token_usage.get("cost_usd", 0),
            cost_breakdown=cost_breakdown or {},
        )
        session.add(result)
        await session.flush()

        finding_ids: list[uuid.UUID] = []
        for f in findings:
            finding = Finding(
                result_id=result.id,
                tenant_id=uuid.UUID(tenant_id),
                pillar=f.get("pillar", "metrics"),
                severity=f.get("severity", "info"),
                dimension=f.get("dimension", "coverage"),
                title=f.get("title", ""),
                description=f.get("description", ""),
                file_path=f.get("file_path"),
                line_start=f.get("line_start"),
                line_end=f.get("line_end"),
                suggestion=f.get("suggestion"),
                estimated_monthly_cost_impact=f.get("estimated_monthly_cost_impact", 0),
            )
            session.add(finding)
            finding_ids.append(finding.id)

        await session.flush()
        enriched: list[dict] = []
        for finding_id, f in zip(finding_ids, findings):
            enriched.append({**f, "id": str(finding_id)})
        result.findings = enriched

    log.info("results_saved_to_db", job_id=job_id, findings_count=len(findings))

    try:
        from apps.agent.tasks.ingest_analysis_history import ingest_analysis_history
        ingest_analysis_history.delay(job_id)
        log.info("ingest_history_enqueued", job_id=job_id)
    except Exception as e:
        log.warning("ingest_history_enqueue_failed", job_id=job_id, error=str(e))


async def _post_pr_comment(request: dict, findings: list[dict], scores: dict) -> None:
    """Format and post the analysis report as a PR comment."""
    global_score = scores.get("global_score") or 0
    grade = "A" if global_score >= 90 else "B" if global_score >= 75 else "C" if global_score >= 60 else "D"

    critical_count = sum(1 for f in findings if f.get("severity") == "critical")
    warning_count = sum(1 for f in findings if f.get("severity") == "warning")

    cost_impact = sum(f.get("estimated_monthly_cost_impact", 0) for f in findings)

    report = f"""## 🔍 Horion Observability Analysis

**Global Score: {global_score}/100 (Grade {grade})**

| Pillar | Score |
|--------|-------|
| Metrics | {scores.get('metrics', 'N/A')}/100 |
| Logs | {scores.get('logs', 'N/A')}/100 |
| Traces | {scores.get('traces', 'N/A')}/100 |

**Found:** {critical_count} critical, {warning_count} warnings
{"⚠️ **Estimated cost impact: $" + f"{cost_impact:.0f}/month**" if cost_impact > 0 else ""}

### Findings

"""

    for f in sorted(findings, key=lambda x: {"critical": 0, "warning": 1, "info": 2}[x.get("severity", "info")]):
        severity_icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(f.get("severity", "info"), "⚪")
        file_ref = f"`{f.get('file_path', 'unknown')}:{f.get('line_start', '?')}`" if f.get("file_path") else ""
        report += f"{severity_icon} **{f.get('title', '')}** {file_ref}\n"
        report += f"> {f.get('description', '')}\n"
        if f.get("suggestion"):
            report += f"\n<details><summary>Suggested fix</summary>\n\n```\n{f['suggestion']}\n```\n</details>\n"
        report += "\n"

    report += "\n---\n*Powered by [Horion](https://horion.pro) — Reliability Engineering Platform.*"

    installation_id = request.get("installation_id")
    full_name = request.get("repo_full_name")
    pr_number = request.get("pr_number")

    if installation_id and full_name and pr_number:
        from apps.api.scm.github import GitHubAdapter
        adapter = GitHubAdapter()
        await adapter.post_report(installation_id, full_name, pr_number, report)
        log.info("pr_comment_posted", repo=full_name, pr=pr_number)
