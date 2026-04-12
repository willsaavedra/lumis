"""Node 8: Generate code suggestions for critical/warning findings."""
from __future__ import annotations

import json
import time
import structlog
from opentelemetry.trace import StatusCode

from apps.agent.nodes.base import publish_progress, publish_llm_call_started, log_llm_call, publish_thought, publish_cost_update
from apps.agent.nodes.instrumentation_hints import constraint_section
from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)

PROMPT_VERSION = "suggestions-v1.3"


# Max findings to generate suggestions for, per analysis type
_SUGGESTION_CAPS: dict[str, int] = {
    "quick":      0,   # quick never reaches this node (graph routing), guard only
    "full":       10,
    "repository": 25,
}


async def generate_suggestions_node(state: AgentState) -> dict:
    """
    Generate code snippets for critical and warning findings.
    Respects analysis_type:
      - quick:      never reached (graph routes quick → score directly); cap=0 as safety guard
      - full:       up to 10 findings
      - repository: up to 25 findings
    """
    analysis_type = state.get("request", {}).get("analysis_type", "full")
    cap = _SUGGESTION_CAPS.get(analysis_type, 10)

    await publish_progress(state, "generating", 82, "Generating code suggestions...", stage_index=8)

    findings = state.get("findings", [])

    if cap == 0:
        log.info(
            "suggestion_skipped",
            reason="quick_type",
            analysis_type=analysis_type,
            findings_count=len(findings),
            job_id=state.get("job_id"),
        )
        await publish_progress(state, "generating", 88, "Suggestions skipped for quick analysis.")
        return {"findings": findings}

    actionable = [
        f for f in findings
        if f.get("severity") in ("critical", "warning")
        and not f.get("suggestion")
        and f.get("file_path")
    ]

    if not actionable:
        log.info(
            "suggestion_skipped",
            reason="no_actionable_findings",
            total_findings=len(findings),
            job_id=state.get("job_id"),
        )
        await publish_progress(state, "generating", 88, "Suggestions complete.")
        return {"findings": findings}

    # Build a file content lookup for context-aware suggestions
    file_contents: dict[str, str] = {
        f["path"]: f.get("content", "")
        for f in state.get("changed_files", [])
        if f.get("content")
    }

    updated_findings = list(findings)
    for i in range(0, min(len(actionable), cap), 5):
        batch = actionable[i:i + 5]
        try:
            results = await _generate_batch_suggestions(batch, file_contents, state)
            for finding, result in zip(batch, results):
                for f in updated_findings:
                    if (f.get("title") == finding.get("title") and
                            f.get("file_path") == finding.get("file_path")):
                        if isinstance(result, dict):
                            f["suggestion"]  = result.get("suggestion") or f.get("suggestion")
                            if result.get("code_before"):
                                f["code_before"] = result["code_before"]
                            if result.get("code_after"):
                                f["code_after"] = result["code_after"]
                        else:
                            f["suggestion"] = result
                        break
        except Exception as exc:
            from opentelemetry import trace
            span = trace.get_current_span()
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, str(exc))
            log.error("suggestion_generation_failed", error=str(exc), exc_info=True)

    await publish_thought(
        state, "generate_suggestions",
        f"Generated code fix suggestions for {min(len(actionable), cap)} finding(s)",
        status="done",
    )
    await publish_cost_update(state, node="generate_suggestions")
    await publish_progress(state, "generating", 88, "Code suggestions generated.", stage_index=8)
    return {"findings": updated_findings}


def _extract_context(content: str, line_start: int, window: int = 15) -> str:
    """Return up to `window` lines around line_start."""
    if not content:
        return ""
    lines = content.splitlines()
    lo = max(0, line_start - window - 1)
    hi = min(len(lines), line_start + window)
    numbered = [f"{lo + j + 1:4d} | {ln}" for j, ln in enumerate(lines[lo:hi])]
    return "\n".join(numbered)


async def _generate_batch_suggestions(
    findings: list[dict],
    file_contents: dict[str, str],
    state: AgentState,
) -> list[dict]:
    """Use Sonnet to generate context-aware code fix suggestions.

    Returns one dict per finding:
      {
        "suggestion":  str,        # short human explanation
        "code_before": str | None, # verbatim lines from the repo that need changing
        "code_after":  str | None, # corrected version of those exact lines
      }
    """
    from apps.agent.core.config import settings
    from apps.agent.llm.chat_completion import chat_complete

    provider = state.get("request", {}).get("llm_provider", "anthropic")
    if provider == "cerebra_ai":
        llm_model = settings.cerebra_ai_model_primary
    else:
        llm_model = settings.anthropic_model_primary

    # Determine primary language from the batch
    lang = "python"
    for f in findings:
        fp = f.get("file_path", "")
        if fp.endswith(".go"):
            lang = "go"
            break
        elif fp.endswith(".py"):
            lang = "python"
            break
        elif fp.endswith((".ts", ".js")):
            lang = "typescript"
            break
        elif fp.endswith(".java"):
            lang = "java"
            break
        elif fp.endswith((".tf", ".hcl")):
            lang = "terraform"
            break
        elif fp.endswith((".yaml", ".yml")):
            lang = "yaml"
            break

    repo_ctx = state.get("repo_context") or {}
    instrumentation = repo_ctx.get("instrumentation") or "otel"

    # IaC repos must not receive application SDK suggestions
    _iac_languages = frozenset({"terraform", "hcl", "bicep", "helm", "pulumi", "jsonnet", "cloudformation"})
    _repo_lang_list = repo_ctx.get("language") or []
    _repo_langs = [l.lower() for l in (_repo_lang_list if isinstance(_repo_lang_list, list) else [_repo_lang_list])]
    _is_iac = (
        (repo_ctx.get("repo_type") or "").strip().lower() == "iac"
        or bool(repo_ctx.get("iac_provider"))
        or any(l in _iac_languages for l in _repo_langs)
        or lang in ("terraform", "yaml", "hcl")
    )

    if _is_iac:
        _provider = repo_ctx.get("iac_provider") or lang
        sdk_constraint = (
            f"\n\n## IaC REPOSITORY — NON-NEGOTIABLE\n"
            f"This is an Infrastructure-as-Code repository ({_provider}). "
            "Files are infrastructure configuration, NOT application source code.\n"
            "NEVER suggest: Python imports, Node.js/npm packages, dd-trace, opentelemetry SDK, "
            "or any application runtime library.\n"
            "ALL fixes MUST be infrastructure-native: Terraform variables, data sources, "
            "Helm values, Kubernetes manifests, or shell/CLI commands."
        )
    else:
        sdk_note = {
            "otel":    f"Use OpenTelemetry SDK for {lang} (vendor-neutral).",
            "datadog": f"Use Datadog dd-trace / ddsketch for {lang} — do NOT introduce OTEL imports.",
            "mixed":   f"Prefer OpenTelemetry SDK for new instrumentation in {lang}; avoid mixing further.",
            "none":    f"Introduce OpenTelemetry SDK for {lang} as the baseline instrumentation.",
            "other":   f"Use the project's existing instrumentation library for {lang}.",
        }.get(instrumentation, f"Use OpenTelemetry SDK for {lang}.")
        sdk_constraint = f"\n- {sdk_note}"

    # Build enriched finding descriptions with surrounding code context
    findings_with_context = []
    for f in findings:
        content = file_contents.get(f.get("file_path", ""), "")
        ctx = _extract_context(content, f.get("line_start", 1))
        # Extract the specific problematic lines for code_before candidate
        line_start = (f.get("line_start") or 1) - 1  # 0-indexed
        line_end = (f.get("line_end") or (line_start + 10))
        lines = content.splitlines()
        raw_lines = lines[max(0, line_start): min(len(lines), line_end)]
        code_candidate = "\n".join(raw_lines).strip()
        findings_with_context.append({
            "title":          f["title"],
            "description":    f["description"],
            "file_path":      f.get("file_path"),
            "line_start":     f.get("line_start"),
            "severity":       f.get("severity"),
            "code_context":   ctx,
            "code_candidate": code_candidate,  # verbatim lines the LLM should treat as code_before
        })

    findings_text = json.dumps(findings_with_context, indent=2)

    system_prompt = f"""You are an expert SRE generating targeted observability fixes in {lang}.
{sdk_constraint}

Rules:
- The fix must be minimal and targeted — do NOT rewrite the entire file.
- code_before: copy the exact lines from `code_candidate` that need to change (verbatim, no line numbers).
  If the finding is purely additive (nothing to remove), set code_before to null.
- code_after: the corrected replacement for those exact lines, using the same indentation.
  If additive, show only the new lines to add.
- suggestion: one sentence explaining what to change and why.
- Be concise. Include only syntactically correct {lang} code."""

    user_prompt = f"""Generate a targeted fix for each finding below.

Return a JSON array — one object per finding, same order:
[
  {{
    "suggestion":  "one-sentence explanation",
    "code_before": "verbatim problematic lines (null if purely additive)",
    "code_after":  "corrected lines or new code to add"
  }},
  ...
]

Findings (with surrounding context and candidate lines):
{findings_text}

Return ONLY the JSON array, no markdown fences."""

    await publish_llm_call_started(
        state,
        "generate_suggestions",
        llm_model,
        detail=f"Suggestions for {len(findings)} finding(s)",
    )
    t0 = time.monotonic()
    resp = await chat_complete(
        system=system_prompt,
        user=user_prompt,
        model=llm_model,
        max_tokens=4000,
        provider=provider,
        base_url=settings.cerebra_ai_base_url,
        api_key=settings.anthropic_api_key if provider == "anthropic" else settings.cerebra_ai_api_key,
        temperature=settings.cerebra_ai_temperature if provider == "cerebra_ai" else 0.3,
        top_p=settings.cerebra_ai_top_p if provider == "cerebra_ai" else 0.9,
        timeout=settings.cerebra_ai_timeout if provider == "cerebra_ai" else 120,
    )
    latency_ms = (time.monotonic() - t0) * 1000

    fallback = {"suggestion": "See documentation for instrumentation guidance.", "code_before": None, "code_after": None}
    results: list[dict] = []
    try:
        raw = resp.text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        for item in parsed:
            if isinstance(item, dict):
                results.append({
                    "suggestion":  item.get("suggestion") or "",
                    "code_before": item.get("code_before") or None,
                    "code_after":  item.get("code_after") or None,
                })
            else:
                results.append({"suggestion": str(item), "code_before": None, "code_after": None})
    except Exception:
        results = [fallback] * len(findings)

    await log_llm_call(
        state=state,
        node="generate_suggestions",
        model=llm_model,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        latency_ms=latency_ms,
        findings_count=len(findings),
        prompt_version=PROMPT_VERSION,
        cached_tokens=getattr(resp, "cached_tokens", 0),
    )
    log.info(
        "suggestion_generated",
        model=llm_model,
        provider=provider,
        findings_count=len(findings),
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        latency_ms=round(latency_ms),
        job_id=state.get("job_id"),
    )

    return results
