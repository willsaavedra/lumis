"""Base utilities for graph nodes."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog

from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)


async def publish_analysis_event(
    job_id: str,
    tenant_id: str,
    stage: str,
    progress_pct: int,
    message: str,
) -> None:
    """Publish a progress or terminal event to Redis pub/sub (same channel as SSE)."""
    try:
        from apps.agent.core.config import settings
        import redis.asyncio as aioredis

        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        channel = f"t:{tenant_id}:analysis:{job_id}:progress"
        event = json.dumps({
            "stage": stage,
            "progress_pct": progress_pct,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await redis.publish(channel, event)
        await redis.aclose()
    except Exception as e:
        log.warning("progress_publish_failed", error=str(e))


async def publish_progress(
    state: AgentState,
    stage: str,
    progress_pct: int,
    message: str,
) -> None:
    """Publish progress event to Redis pub/sub for SSE streaming."""
    await publish_analysis_event(
        str(state["job_id"]),
        str(state["tenant_id"]),
        stage,
        progress_pct,
        message,
    )


def log_llm_call(
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
    Log each LLM call with full metadata for quality tracking and A/B prompt testing.
    Updates aggregate token_usage in state and emits a structured log event.

    Schema matches the tuning pipeline spec:
      analysis_id, node, model, input_tokens, output_tokens, latency_ms,
      cost_usd, findings_count, prompt_version, cache_hit, timestamp
    """
    try:
        # Approximate cost per model family.
        # CerebraAI is self-hosted — monetary cost is $0 (infra billed separately).
        provider = state.get("request", {}).get("llm_provider", "anthropic")
        if provider == "cerebra_ai":
            cost = 0.0
        elif "haiku" in model.lower():
            cost = (input_tokens * 0.8 + output_tokens * 4.0) / 1_000_000
        else:
            cost = (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000

        # Update aggregate usage in state (mutated in-place — safe inside a node)
        usage = state.get("token_usage") or {}
        usage["input_tokens"] = usage.get("input_tokens", 0) + input_tokens
        usage["output_tokens"] = usage.get("output_tokens", 0) + output_tokens
        usage["llm_calls"] = usage.get("llm_calls", 0) + 1
        usage["cost_usd"] = round(usage.get("cost_usd", 0.0) + cost, 6)
        state["token_usage"] = usage  # type: ignore[index]

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
