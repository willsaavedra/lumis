"""LangGraph graph definition for observability analysis."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import structlog
from langgraph.graph import END, START, StateGraph

from apps.agent.schemas import AgentState
from apps.agent.nodes import (
    clone_repo_node,
    context_discovery_node,
    pre_triage_node,
    parse_ast_node,
    fetch_dd_coverage_node,
    retrieve_context_node,
    analyze_coverage_node,
    analyze_efficiency_node,
    analyze_iac_node,
    deduplicate_node,
    diff_crossrun_node,
    score_node,
    generate_suggestions_node,
    post_report_node,
)
from apps.agent.nodes.analyze_iac import has_iac_files
from apps.agent.nodes.expand_context import expand_context_node

log = structlog.get_logger(__name__)


def _route_after_clone(state: AgentState) -> str:
    """After cloning, route to context discovery when context is missing or stale."""
    analysis_type = state.get("request", {}).get("analysis_type", "full")
    if analysis_type == "context":
        return "context_discovery"
    if analysis_type in ("full", "repository"):
        ctx = state.get("repo_context") or {}
        if not ctx.get("context_summary"):
            return "context_discovery"
    return "pre_triage"


def _route_after_context_discovery(state: AgentState) -> str:
    """Standalone context jobs exit; inline context continues to pre_triage."""
    analysis_type = state.get("request", {}).get("analysis_type", "full")
    if analysis_type == "context":
        return END
    return "pre_triage"



def _route_after_coverage(state: AgentState) -> str:
    """Quick skips efficiency scoring — goes straight to deduplicate → score → post_report.
    Also handles autonomous context expansion (max 1 per run)."""
    if state.get("expansion_requested") and state.get("expansion_count", 0) < 1:
        return "expand_context"
    analysis_type = state.get("request", {}).get("analysis_type", "full")
    if analysis_type == "quick":
        return "deduplicate"
    return "analyze_efficiency"


def _route_after_triage_with_iac(state: AgentState) -> str:
    """
    After triage:
      - quick → retrieve_context (limited RAG for history) → analyze_coverage
      - IaC repo or IaC files detected → analyze_iac (runs before/alongside coverage)
      - otherwise → parse_ast (full pipeline)
    """
    analysis_type = state.get("request", {}).get("analysis_type", "full")
    if analysis_type == "quick":
        return "retrieve_context"
    if has_iac_files(state):
        return "analyze_iac"
    return "parse_ast"


def build_graph() -> StateGraph:
    """Build and compile the LangGraph analysis pipeline."""
    workflow = StateGraph(AgentState)

    # Add all nodes
    workflow.add_node("clone_repo", clone_repo_node)
    workflow.add_node("context_discovery", context_discovery_node)
    workflow.add_node("pre_triage", pre_triage_node)
    workflow.add_node("parse_ast", parse_ast_node)
    workflow.add_node("fetch_dd_coverage", fetch_dd_coverage_node)
    workflow.add_node("retrieve_context", retrieve_context_node)
    workflow.add_node("analyze_coverage", analyze_coverage_node)
    workflow.add_node("analyze_iac", analyze_iac_node)
    workflow.add_node("analyze_efficiency", analyze_efficiency_node)
    workflow.add_node("deduplicate", deduplicate_node)
    workflow.add_node("diff_crossrun", diff_crossrun_node)
    workflow.add_node("score", score_node)
    workflow.add_node("generate_suggestions", generate_suggestions_node)
    workflow.add_node("post_report", post_report_node)
    workflow.add_node("expand_context", expand_context_node)

    # Entry point
    workflow.add_edge(START, "clone_repo")

    # Branch: context discovery vs full analysis
    workflow.add_conditional_edges("clone_repo", _route_after_clone, {
        "context_discovery": "context_discovery",
        "pre_triage": "pre_triage",
    })

    # Standalone context jobs exit; inline context continues the pipeline
    workflow.add_conditional_edges("context_discovery", _route_after_context_discovery, {
        END: END,
        "pre_triage": "pre_triage",
    })

    # Branch after triage:
    #   quick     → retrieve_context (limited RAG) → analyze_coverage
    #   IaC files → analyze_iac → retrieve_context → analyze_coverage
    #   full/repo → parse_ast → fetch_dd → retrieve_context → analyze_coverage
    workflow.add_conditional_edges("pre_triage", _route_after_triage_with_iac, {
        "retrieve_context": "retrieve_context",   # quick (limited RAG for history)
        "analyze_iac": "analyze_iac",             # IaC-only repos / mixed changesets
        "parse_ast": "parse_ast",                 # full / repository (no IaC)
    })

    # Full / repository pipeline (parse_ast → fetch_dd → retrieve_context → analyze_coverage)
    workflow.add_edge("parse_ast", "fetch_dd_coverage")
    workflow.add_edge("fetch_dd_coverage", "retrieve_context")
    workflow.add_edge("retrieve_context", "analyze_coverage")

    # IaC path also benefits from RAG context before coverage analysis
    workflow.add_edge("analyze_iac", "retrieve_context")

    # Quick skips efficiency but still deduplicates; full/repository run efficiency first
    # expand_context loops back to analyze_coverage for re-analysis with additional files
    workflow.add_conditional_edges("analyze_coverage", _route_after_coverage, {
        "deduplicate": "deduplicate",                # quick
        "analyze_efficiency": "analyze_efficiency",  # full / repository
        "expand_context": "expand_context",          # autonomous expansion
    })
    workflow.add_edge("expand_context", "analyze_coverage")

    workflow.add_edge("analyze_efficiency", "deduplicate")
    workflow.add_edge("deduplicate", "diff_crossrun")
    workflow.add_edge("diff_crossrun", "score")
    workflow.add_edge("score", "generate_suggestions")
    workflow.add_edge("generate_suggestions", "post_report")
    workflow.add_edge("post_report", END)

    return workflow.compile()


# Singleton compiled graph
analysis_graph = build_graph()


async def _persist_analysis_failure(job_id: str, tenant_id: str, err: str) -> None:
    """Mark job failed in DB and emit timeline/SSE event (agent runs decoupled from worker)."""
    import uuid as uuid_mod
    from datetime import datetime, timezone

    from sqlalchemy import select

    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob
    from apps.agent.nodes.base import publish_analysis_event

    msg = (err or "Analysis failed.")[:2000]
    async with AsyncSessionFactory() as session:
        result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid_mod.UUID(job_id)))
        job = result.scalar_one_or_none()
        if job:
            job.status = "failed"
            job.error_message = msg
            job.completed_at = datetime.now(timezone.utc)
        await session.commit()
    await publish_analysis_event(job_id, tenant_id, "failed", 0, msg, event_type="step")


async def run_analysis_graph(job_id: str) -> None:
    """
    Entry point for running analysis. Invoked by the agent HTTP server (or locally).
    Loads the job from DB, builds initial state, runs the graph.
    """
    log.info("analysis_graph_started", job_id=job_id)

    failure_tenant_id: str | None = None

    try:
        from apps.api.core.database import AsyncSessionFactory
        from apps.api.models.analysis import AnalysisJob
        from apps.api.models.scm import Repository, ScmConnection
        from sqlalchemy import select

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()

        if not job:
            log.error("analysis_job_not_found", job_id=job_id)
            return

        failure_tenant_id = str(job.tenant_id)

        async with AsyncSessionFactory() as session:
            repo_result = await session.execute(select(Repository).where(Repository.id == job.repo_id))
            repo = repo_result.scalar_one_or_none()

        if not repo:
            log.error("repo_not_found", job_id=job_id)
            return

        conn = None
        if repo.scm_connection_id:
            async with AsyncSessionFactory() as session:
                conn_result = await session.execute(
                    select(ScmConnection).where(ScmConnection.id == repo.scm_connection_id)
                )
                conn = conn_result.scalar_one_or_none()

        installation_id = conn.installation_id if conn else None
        scm_type = (conn.scm_type if conn else "github") or "github"

        from apps.api.core.config import settings as app_settings

        def _default_clone_url() -> str:
            if repo.clone_url:
                return repo.clone_url
            fn = repo.full_name
            if scm_type == "gitlab":
                base = app_settings.gitlab_base_url.rstrip("/")
                return f"{base}/{fn}.git"
            if scm_type == "bitbucket":
                return f"https://bitbucket.org/{fn}.git"
            return f"https://github.com/{fn}.git"

        # Load repo tags for context injection
        repo_tags_list: list[dict] = []
        try:
            from apps.api.models.tag_system import RepoTag
            async with AsyncSessionFactory() as session:
                tag_result = await session.execute(
                    select(RepoTag).where(RepoTag.repo_id == repo.id)
                )
                repo_tags_list = [{"key": t.key, "value": t.value} for t in tag_result.scalars().all()]
        except Exception as e:
            log.warning("load_repo_tags_failed", job_id=job_id, error=str(e))

        repo_context = {
            "repo_type": getattr(repo, "repo_type", None),
            "app_subtype": getattr(repo, "app_subtype", None),
            "iac_provider": getattr(repo, "iac_provider", None),
            "language": getattr(repo, "language", None),
            "observability_backend": getattr(repo, "observability_backend", None),
            "instrumentation": getattr(repo, "instrumentation", None),
            "obs_metadata": getattr(repo, "obs_metadata", None),
            "context_summary": getattr(repo, "context_summary", None),
            "app_map": getattr(repo, "app_map", None),
            "tags": repo_tags_list,
        }

        initial_state: AgentState = {
            "job_id": job_id,
            "tenant_id": str(job.tenant_id),
            "request": {
                "job_id": job_id,
                "tenant_id": str(job.tenant_id),
                "repo_id": str(job.repo_id),
                "repo_full_name": repo.full_name,
                "clone_url": _default_clone_url(),
                "ref": job.branch_ref or repo.default_branch,
                "pr_number": job.pr_number,
                "commit_sha": job.commit_sha,
                "changed_files": job.changed_files.get("files", []) if job.changed_files else [],
                "analysis_type": job.analysis_type,
                "scope_type": getattr(job, "scope_type", None) or ("selection" if job.analysis_type == "quick" else "full_repo"),
                "llm_provider": getattr(job, "llm_provider", "anthropic") or "anthropic",
                "installation_id": installation_id,
                "scm_type": scm_type,
                "repo_context": repo_context,
                "user_answers": getattr(job, "user_answers", None) or {},
            },
            "repo_path": None,
            "changed_files": [],
            "call_graph": None,
            "coverage_map": None,
            "dd_coverage": None,
            "findings": [],
            "efficiency_scores": {},
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "llm_calls": 0, "cost_usd": 0.0, "by_node": {}},
            "messages": [],
            "error": None,
            "stage": "starting",
            "progress_pct": 0,
            "repo_context": repo_context,
            "suppressed": [],
            "previous_job_id": None,
            "crossrun_summary": None,
            "rag_context": None,
            "analysis_manifest": None,
            "expansion_requested": None,
            "expansion_count": 0,
        }

        # Run graph
        final_state = await analysis_graph.ainvoke(initial_state)
        log.info("analysis_graph_completed", job_id=job_id, score=final_state.get("efficiency_scores", {}).get("global_score"))

    except Exception as e:
        import traceback
        log.error("analysis_graph_failed", job_id=job_id, error=str(e), traceback=traceback.format_exc())
        if failure_tenant_id:
            try:
                await _persist_analysis_failure(job_id, failure_tenant_id, str(e))
            except Exception as persist_exc:
                log.warning("persist_analysis_failure_failed", job_id=job_id, error=str(persist_exc))
        raise
