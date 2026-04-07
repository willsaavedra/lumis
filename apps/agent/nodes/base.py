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
) -> None:
    """Publish pipeline step to Redis (live + timeline)."""
    await publish_analysis_event(
        str(state["job_id"]),
        str(state["tenant_id"]),
        stage,
        progress_pct,
        message,
        event_type="step",
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
