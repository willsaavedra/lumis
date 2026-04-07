"""Base utilities for graph nodes."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog

from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)

_TIMELINE_TTL_SEC = 604800  # 7 days


def _timeline_key(tenant_id: str, job_id: str) -> str:
    return f"t:{tenant_id}:analysis:{job_id}:timeline"


async def publish_analysis_event(
    job_id: str,
    tenant_id: str,
    stage: str,
    progress_pct: int,
    message: str,
    *,
    event_type: str = "step",
    extra: dict | None = None,
) -> None:
    """Publish progress to Redis pub/sub and append to persistent timeline (SSE replay on refresh)."""
    try:
        from apps.agent.core.config import settings
        import redis.asyncio as aioredis

        event_obj: dict = {
            "event_type": event_type,
            "stage": stage,
            "progress_pct": progress_pct,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            event_obj.update(extra)

        event = json.dumps(event_obj, ensure_ascii=False)
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        channel = f"t:{tenant_id}:analysis:{job_id}:progress"
        tk = _timeline_key(tenant_id, job_id)
        try:
            await redis.publish(channel, event)
            await redis.rpush(tk, event)
            await redis.expire(tk, _TIMELINE_TTL_SEC)
        finally:
            await redis.aclose()
    except Exception as e:
        log.warning("progress_publish_failed", error=str(e))


async def publish_progress(
    state: AgentState,
    stage: str,
    progress_pct: int,
    message: str,
    *,
    stage_index: int | None = None,
    files_analyzed: int | None = None,
    files_total: int | None = None,
    current_file: str | None = None,
) -> None:
    """Publish pipeline step to Redis (live + timeline)."""
    extra: dict = {}
    if stage_index is not None:
        extra["stage_index"] = stage_index
    if files_analyzed is not None:
        extra["files_analyzed"] = files_analyzed
    if files_total is not None:
        extra["files_total"] = files_total
    if current_file is not None:
        extra["current_file"] = current_file

    usage = state.get("token_usage") or {}
    extra["tokens_input"] = usage.get("input_tokens", 0)
    extra["tokens_output"] = usage.get("output_tokens", 0)
    extra["cost_usd_so_far"] = usage.get("cost_usd", 0.0)

    findings = state.get("findings") or []
    extra["findings_count"] = {
        "critical": sum(1 for f in findings if f.get("severity") == "critical"),
        "warning": sum(1 for f in findings if f.get("severity") == "warning"),
        "info": sum(1 for f in findings if f.get("severity") == "info"),
    }

    state["progress_pct"] = progress_pct  # type: ignore[index]

    await publish_analysis_event(
        str(state["job_id"]),
        str(state["tenant_id"]),
        stage,
        progress_pct,
        message,
        event_type="progress",
        extra=extra,
    )


async def publish_thought(
    state: AgentState,
    node: str,
    text: str,
    *,
    model: str | None = None,
    status: str = "done",
    files: list[str] | None = None,
) -> None:
    """Emit a reasoning thought for the live stream UI."""
    extra: dict = {
        "node": node,
        "model": model,
        "status": status,
        "text": text,
    }
    if files:
        extra["files"] = files
    await publish_analysis_event(
        str(state["job_id"]),
        str(state["tenant_id"]),
        state.get("stage") or "",
        int(state.get("progress_pct") or 0),
        text[:200],
        event_type="thought",
        extra=extra,
    )


async def publish_finding(
    state: AgentState,
    finding: dict,
    node: str,
) -> None:
    """Emit a newly discovered finding for real-time display."""
    extra: dict = {
        "id": finding.get("id") or "",
        "severity": finding.get("severity", "info"),
        "pillar": finding.get("pillar", ""),
        "title": finding.get("title", ""),
        "description": finding.get("description", ""),
        "file_path": finding.get("file_path", ""),
        "line_start": finding.get("line_start"),
        "line_end": finding.get("line_end"),
        "node": node,
    }
    await publish_analysis_event(
        str(state["job_id"]),
        str(state["tenant_id"]),
        state.get("stage") or "",
        int(state.get("progress_pct") or 0),
        finding.get("title", ""),
        event_type="finding",
        extra=extra,
    )


async def publish_file_status(
    state: AgentState,
    file: str,
    file_status: str,
    language: str = "",
) -> None:
    """Emit file scanning/done/skipped status for live file queue."""
    await publish_analysis_event(
        str(state["job_id"]),
        str(state["tenant_id"]),
        state.get("stage") or "",
        int(state.get("progress_pct") or 0),
        f"{file}: {file_status}",
        event_type="file_status",
        extra={"file": file, "status": file_status, "language": language},
    )


async def publish_cost_update(state: AgentState) -> None:
    """Emit current cost breakdown from token_usage."""
    usage = state.get("token_usage") or {}
    total = usage.get("cost_usd", 0.0)

    haiku_cost = 0.0
    sonnet_cost = 0.0
    for _call in (state.get("_llm_cost_log") or []):
        if "haiku" in (_call.get("model") or "").lower():
            haiku_cost += _call.get("cost", 0.0)
        else:
            sonnet_cost += _call.get("cost", 0.0)

    if haiku_cost == 0 and sonnet_cost == 0:
        sonnet_cost = total

    await publish_analysis_event(
        str(state["job_id"]),
        str(state["tenant_id"]),
        state.get("stage") or "",
        int(state.get("progress_pct") or 0),
        f"Cost: ${total:.3f}",
        event_type="cost_update",
        extra={
            "haiku_usd": round(haiku_cost, 4),
            "sonnet_usd": round(sonnet_cost, 4),
            "embeddings_usd": 0.0,
            "total_usd": round(total, 4),
            "credits_consumed": max(1, int(total / 0.05)) if total > 0 else 0,
        },
    )


async def publish_done(
    state: AgentState,
    score_global: int | None = None,
) -> None:
    """Emit terminal done event with score and redirect URL."""
    job_id = str(state["job_id"])
    await publish_analysis_event(
        job_id,
        str(state["tenant_id"]),
        "done",
        100,
        "Analysis complete!",
        event_type="done",
        extra={
            "analysis_id": job_id,
            "score_global": score_global or 0,
            "redirect_to": f"/analyses/{job_id}",
        },
    )


async def publish_llm_call_started(
    state: AgentState,
    node: str,
    model: str,
    *,
    detail: str | None = None,
) -> None:
    """Notify UI that an LLM request is in flight (before streaming/completion)."""
    msg = detail or f"LLM request — {node}"
    await publish_analysis_event(
        str(state["job_id"]),
        str(state["tenant_id"]),
        "llm",
        int(state.get("progress_pct") or 0),
        msg,
        event_type="llm",
        extra={
            "llm_phase": "started",
            "node": node,
            "model": model,
            "llm_streaming": True,
        },
    )


async def log_llm_call(
    state: AgentState,
    node: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    findings_count: int,
    prompt_version: str,
    cache_hit: bool = False,
) -> None:
    """
    Log each LLM call with full metadata; update token_usage; emit timeline + structured log.
    """
    try:
        provider = state.get("request", {}).get("llm_provider", "anthropic")
        if provider == "cerebra_ai":
            cost = 0.0
        elif "haiku" in model.lower():
            cost = (input_tokens * 0.8 + output_tokens * 4.0) / 1_000_000
        else:
            cost = (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000

        usage = state.get("token_usage") or {}
        usage["input_tokens"] = usage.get("input_tokens", 0) + input_tokens
        usage["output_tokens"] = usage.get("output_tokens", 0) + output_tokens
        usage["llm_calls"] = usage.get("llm_calls", 0) + 1
        usage["cost_usd"] = round(usage.get("cost_usd", 0.0) + cost, 6)
        state["token_usage"] = usage  # type: ignore[index]

        summary = (
            f"LLM completed — {node}: {input_tokens} in / {output_tokens} out tokens, "
            f"{latency_ms:.0f} ms · {findings_count} findings"
        )
        await publish_analysis_event(
            str(state["job_id"]),
            str(state["tenant_id"]),
            "llm",
            int(state.get("progress_pct") or 0),
            summary,
            event_type="llm",
            extra={
                "llm_phase": "completed",
                "node": node,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": round(latency_ms, 2),
                "findings_count": findings_count,
                "prompt_version": prompt_version,
                "llm_streaming": False,
            },
        )

        log.info(
            "llm_call",
            analysis_id=state.get("job_id"),
            node=node,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round(latency_ms),
            cost_usd=round(cost, 6),
            findings_count=findings_count,
            prompt_version=prompt_version,
            cache_hit=cache_hit,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        log.warning("log_llm_call_failed", error=str(exc))
