"""Unified LLM adapter — routes to Anthropic SDK or OpenAI-compatible endpoints."""
from __future__ import annotations

from dataclasses import dataclass

import structlog

log = structlog.get_logger(__name__)


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0


async def chat_complete(
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    *,
    provider: str,
    base_url: str = "",
    api_key: str = "",
    temperature: float = 0.3,
    top_p: float = 0.9,
    timeout: int = 120,
    assistant_prefill: str | None = None,
) -> LLMResponse:
    """
    Single async entry-point for all LLM chat calls.

    provider="anthropic"  → Anthropic SDK (messages API) with prompt caching
    provider="cerebra_ai" → OpenAI-compatible POST /v1/chat/completions via httpx
    """
    if provider == "anthropic":
        return await _call_anthropic(
            system=system,
            user=user,
            model=model,
            max_tokens=max_tokens,
            api_key=api_key,
            assistant_prefill=assistant_prefill,
        )
    if provider == "cerebra_ai":
        return await _call_openai_compatible(
            system=system,
            user=user,
            model=model,
            max_tokens=max_tokens,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            top_p=top_p,
            timeout=timeout,
        )
    raise ValueError(f"Unknown LLM provider: {provider}")


async def _call_anthropic(
    *,
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    api_key: str,
    assistant_prefill: str | None = None,
) -> LLMResponse:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)

    messages: list[dict] = [{"role": "user", "content": user}]
    if assistant_prefill:
        messages.append({"role": "assistant", "content": assistant_prefill})

    # Enable prompt caching on the system prompt: mark the last block with
    # cache_control so the Anthropic API can reuse it across calls for the
    # same tenant.  The system param is passed as a content-block list.
    system_blocks = [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    message = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_blocks,
        messages=messages,
    )

    text = message.content[0].text
    if assistant_prefill:
        text = assistant_prefill + text

    cached_tokens = getattr(message.usage, "cache_read_input_tokens", 0) or 0

    return LLMResponse(
        text=text,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        cached_tokens=cached_tokens,
    )


async def _call_openai_compatible(
    *,
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    base_url: str,
    api_key: str,
    temperature: float,
    top_p: float,
    timeout: int,
) -> LLMResponse:
    import httpx

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "stream": False,
    }

    url = f"{base_url.rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    text = data["choices"][0]["message"]["content"]
    if text is None:
        finish_reason = data["choices"][0].get("finish_reason", "unknown")
        log.warning(
            "llm_null_content",
            model=model,
            finish_reason=finish_reason,
        )
        text = ""
    usage = data.get("usage", {})

    return LLMResponse(
        text=text,
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        cached_tokens=0,
    )
