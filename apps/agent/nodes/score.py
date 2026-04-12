"""Node 7: Calculate efficiency scores."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import structlog

from apps.agent.nodes.base import publish_progress, publish_thought
from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Instrumentation detection — determines whether metrics/traces are meaningful
# ---------------------------------------------------------------------------

# App-level SDK imports: any of these in source files indicates instrumentation
_APP_SDK_RE = re.compile(
    r"opentelemetry"
    r"|ddtrace"
    r"|dd-trace"
    r"|dd\.tracer"
    r"|datadog\.tracer"
    r"|opentracing"
    r"|opencensus"
    r"|openmetrics"
    r"|prometheus_client"
    r"|prom-client"
    r"|prom\.NewCounter"
    r"|statsd\."
    r"|go\.opentelemetry\.io"
    r"|gopkg\.in/DataDog/dd-trace-go"
    r"|io\.opentelemetry"
    r"|io\.opentracing"
    r"|@opentelemetry/"
    r"|datadog-lambda"
    r"|micrometer"
    r"|otel\.trace"
    r"|tracer\.start_as_current_span"
    r"|tracer\.startActiveSpan"
    r"|startActiveSpan",
    re.IGNORECASE,
)

# Infra-level agent: DataDog Agent or OTel Collector present in config/compose
_INFRA_AGENT_RE = re.compile(
    r"datadog[/_-]agent"
    r"|datadog/agent:"
    r"|otel[/_-]collector"
    r"|opentelemetry[/_-]collector"
    r"|otelcol"
    r"|otelcontribcol"
    r"|otel/opentelemetry-collector",
    re.IGNORECASE,
)

# Default penalty values — overridden by score_config.json if present
_DEFAULT_DIMENSION_PENALTIES = {
    "critical": 20,
    "warning": 10,
    "info": 3,
}
_DEFAULT_PILLAR_PENALTIES = {
    "critical": 25,
    "warning": 12,
    "info": 5,
}

# Optional config file path (relative to project root or absolute)
_CONFIG_PATH = os.environ.get("SCORE_CONFIG_PATH", "score_config.json")


def _load_score_config() -> dict:
    """Load calibrated score penalties from score_config.json, falling back to defaults."""
    try:
        path = Path(_CONFIG_PATH)
        if path.exists():
            with path.open() as f:
                cfg = json.load(f)
            log.debug("score_config_loaded", path=str(path))
            return cfg
    except Exception as e:
        log.warning("score_config_load_failed", error=str(e))
    return {}


_SCORE_CONFIG = _load_score_config()


def _detect_instrumentation(state: AgentState) -> dict:
    """
    Detect whether the repository has any observable instrumentation.

    Priority order:
      1. Explicit `instrumentation` field in repo_context (user-configured)
      2. Scan all analyzed file contents for SDK import patterns
      3. Check for infra-agent configs in files

    Returns a dict with:
      - has_app_sdk (bool)   — OTEL/DD/OT/Prometheus SDK found in source files
      - has_infra_agent (bool) — DataDog Agent or OTel Collector config found
      - source (str)         — "explicit" | "explicit_none" | "scan" | "none"
    """
    repo_context = state.get("repo_context") or {}
    instrumentation = (repo_context.get("instrumentation") or "").strip().lower()

    # 1. Explicitly configured by the user
    if instrumentation and instrumentation != "none":
        return {"has_app_sdk": True, "has_infra_agent": False, "source": "explicit"}
    if instrumentation == "none":
        return {"has_app_sdk": False, "has_infra_agent": False, "source": "explicit_none"}

    # 2. Scan analyzed file contents
    changed_files = state.get("changed_files", [])
    combined = "\n".join(
        f.get("content") or "" for f in changed_files if f.get("content")
    )

    has_app_sdk = bool(_APP_SDK_RE.search(combined))
    has_infra_agent = bool(_INFRA_AGENT_RE.search(combined))

    return {
        "has_app_sdk": has_app_sdk,
        "has_infra_agent": has_infra_agent,
        "source": "scan" if (has_app_sdk or has_infra_agent) else "none",
    }


async def score_node(state: AgentState) -> dict:
    """Calculate observability scores (0-100) for each pillar."""
    await publish_progress(state, "scoring", 75, "Calculating scores...", stage_index=8)

    findings = state.get("findings", [])

    # If no files were actually analyzed (loaded with content), scores are meaningless.
    # Return null scores rather than a misleading 100/100.
    changed_files = state.get("changed_files", [])
    analyzed = [f for f in changed_files if f.get("relevance_score", 0) >= 1 and f.get("content")]
    if not analyzed:
        log.warning("no_files_analyzed_skipping_scores", job_id=state.get("job_id"))
        await publish_progress(state, "scoring", 80, "No relevant files to score.")
        return {"efficiency_scores": {
            "cost": None, "snr": None, "pipeline": None, "compliance": None,
            "metrics": None, "logs": None, "traces": None, "global_score": None,
        }}

    # Detect instrumentation presence — metrics and traces require an SDK or agent
    instr = _detect_instrumentation(state)
    repo_context = state.get("repo_context") or {}
    is_infra_repo = (repo_context.get("repo_type") or "").lower() in ("infra", "iac")

    log.info(
        "instrumentation_detected",
        has_app_sdk=instr["has_app_sdk"],
        has_infra_agent=instr["has_infra_agent"],
        source=instr["source"],
        is_infra_repo=is_infra_repo,
        job_id=state.get("job_id"),
    )

    # Compute dimension scores (independent of instrumentation)
    cost_score = _score_dimension(findings, "cost")
    snr_score = _score_dimension(findings, "snr")
    pipeline_score = _score_dimension(findings, "pipeline")
    compliance_score = _score_dimension(findings, "compliance")

    # Compute pillar scores
    metrics_score = _score_pillar(findings, "metrics")
    logs_score = _score_pillar(findings, "logs")
    traces_score = _score_pillar(findings, "traces")

    # ---------------------------------------------------------------------------
    # Instrumentation gate: metrics and traces REQUIRE active instrumentation.
    #
    # App services need an SDK (OTEL / ddtrace / Prometheus / OpenTracing).
    # Infra repos can rely on an agent (DD Agent / OTel Collector) for metrics;
    # traces are still app-level and require an SDK.
    # ---------------------------------------------------------------------------
    if not instr["has_app_sdk"] and not instr["has_infra_agent"]:
        # No instrumentation detected at all → both pillars are zero
        metrics_score = 0
        traces_score = 0
        log.warning(
            "no_instrumentation_zeroing_metrics_traces",
            source=instr["source"],
            job_id=state.get("job_id"),
        )
    elif not instr["has_app_sdk"]:
        # Infra agent present but no app SDK → traces require app SDK, zero them
        # Metrics can be partially scored (infra metrics may exist)
        traces_score = 0
        log.info(
            "no_app_sdk_zeroing_traces",
            has_infra_agent=instr["has_infra_agent"],
            job_id=state.get("job_id"),
        )

    # Global score = weighted average of pillar scores
    global_score = int(
        metrics_score * 0.35
        + logs_score * 0.35
        + traces_score * 0.30
    )

    # ── Tag-aware scoring modifiers ─────────────────────────────────────
    tag_modifiers_applied: list[str] = []
    try:
        analysis_tags = await _load_analysis_tags(state)
        tag_by_key = {t["key"]: t["value"] for t in analysis_tags}
        env = tag_by_key.get("env", "").lower()

        if env == "staging":
            boost = 3
            global_score = min(100, global_score + boost)
            tag_modifiers_applied.append(f"staging relaxation +{boost}")

        if tag_modifiers_applied:
            log.info("tag_modifiers_applied", modifiers=tag_modifiers_applied, job_id=state.get("job_id"))
    except Exception as e:
        log.warning("tag_modifier_failed", error=str(e), job_id=state.get("job_id"))

    scores = {
        "cost": cost_score,
        "snr": snr_score,
        "pipeline": pipeline_score,
        "compliance": compliance_score,
        "metrics": metrics_score,
        "logs": logs_score,
        "traces": traces_score,
        "global_score": global_score,
        "instrumentation_detected": instr["has_app_sdk"] or instr["has_infra_agent"],
    }

    log.info("scores_calculated", global_score=global_score, scores=scores)
    await publish_thought(
        state, "score",
        f"Global score: {global_score}/100 — Metrics: {metrics_score}, Logs: {logs_score}, Traces: {traces_score}",
        status="done",
    )
    await publish_progress(state, "scoring", 80, f"Global score: {global_score}/100", stage_index=8)
    return {"efficiency_scores": scores}


def _penalty(kind: str, severity: str, pillar_or_dim: str) -> int:
    """
    Return the penalty for a finding of a given severity.
    Reads from _SCORE_CONFIG (calibrated) with fallback to defaults.

    Config format (score_config.json):
      {
        "dimension_penalties": {"critical": 20, "warning": 10, "info": 3},
        "pillar_penalties": {
          "metrics": {"critical": 25, "warning": 12, "info": 5},
          "logs":    {"critical": 18, "warning": 10, "info": 4}
        }
      }
    """
    if kind == "dimension":
        cfg = _SCORE_CONFIG.get("dimension_penalties", {})
        return cfg.get(severity, _DEFAULT_DIMENSION_PENALTIES.get(severity, 5))
    # pillar — try per-pillar override first, then global pillar penalties
    pillar_cfg = _SCORE_CONFIG.get("pillar_penalties", {}).get(pillar_or_dim, {})
    if not pillar_cfg:
        pillar_cfg = _SCORE_CONFIG.get("pillar_penalties", {})
    return pillar_cfg.get(severity, _DEFAULT_PILLAR_PENALTIES.get(severity, 5))


def _score_dimension(findings: list[dict], dimension: str) -> int:
    score = 100
    for f in (f for f in findings if f.get("dimension") == dimension):
        score -= _penalty("dimension", f.get("severity", "info"), dimension)
    return max(0, score)


def _score_pillar(findings: list[dict], pillar: str) -> int:
    score = 100
    for f in (f for f in findings if f.get("pillar") == pillar):
        score -= _penalty("pillar", f.get("severity", "info"), pillar)
    return max(0, score)


async def _load_analysis_tags(state: AgentState) -> list[dict]:
    """Load analysis_tags for the current job from the database."""
    job_id = state.get("job_id")
    tenant_id = state.get("tenant_id")
    if not job_id or not tenant_id:
        return []

    import uuid as _uuid

    from sqlalchemy import select

    from apps.api.core.database import get_session_with_tenant
    from apps.api.models.tag_system import AnalysisTag

    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(AnalysisTag.key, AnalysisTag.value).where(
                AnalysisTag.job_id == _uuid.UUID(job_id),
            )
        )
        return [{"key": r.key, "value": r.value} for r in result.all()]


