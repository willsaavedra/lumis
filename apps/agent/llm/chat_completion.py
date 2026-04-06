"""Unified async LLM chat completion adapter.

Supports two providers:
  - "anthropic"  : Anthropic Messages API (claude-*)
  - "cerebra_ai" : OpenAI-compatible REST endpoint (vLLM / Qwen self-hosted)

Usage:
    from apps.agent.llm.chat_completion import chat_complete, LLMResponse

    resp: LLMResponse = await chat_complete(
        system="You are ...",
        user="Analyze this code ...",
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        provider="anthropic",
        api_key=settings.anthropic_api_key,
    )
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger(__name__)


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int


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
) -> LLMResponse:
    """Route a chat completion request to the appropriate LLM backend.

    Args:
        system: System prompt text.
        user: User message text.
        model: Model identifier (e.g. "claude-sonnet-4-20250514" or "Qwen/Qwen3.5-35B-A3B-FP8").
        max_tokens: Maximum tokens in the completion.
        provider: "anthropic" or "cerebra_ai".
        base_url: Base URL for OpenAI-compatible endpoint (used when provider="cerebra_ai").
        api_key: API key for the provider (may be empty for self-hosted).
        temperature: Sampling temperature.
        top_p: Nucleus sampling parameter.
        timeout: Request timeout in seconds.

    Returns:
        LLMResponse with the completion text and token counts.

    Raises:
        ValueError: If provider is unknown.
        httpx.HTTPStatusError: On non-2xx responses from CerebraAI endpoint.
        anthropic.APIError: On Anthropic API errors.
    """
    if provider == "anthropic":
        return await _call_anthropic(
            system=system,
            user=user,
            model=model,
            max_tokens=max_tokens,
            api_key=api_key,
            temperature=temperature,
            top_p=top_p,
            timeout=timeout,
        )
    elif provider == "cerebra_ai":
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
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Expected 'anthropic' or 'cerebra_ai'.")


async def _call_anthropic(
    *,
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    api_key: str,
    temperature: float,
    top_p: float,
    timeout: int,
) -> LLMResponse:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key, timeout=float(timeout))
    message = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=temperature,
        top_p=top_p,
    )
    text = message.content[0].text if message.content else ""
    return LLMResponse(
        text=text,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
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
    url = base_url.rstrip("/") + "/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }

    async with httpx.AsyncClient(timeout=float(timeout)) as client:
        response = await client.post(url, headers=headers, content=json.dumps(payload))
        response.raise_for_status()
        data = response.json()

    choice = data["choices"][0]
    text = choice["message"]["content"] or ""
    usage = data.get("usage", {})
    return LLMResponse(
        text=text,
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
    )
