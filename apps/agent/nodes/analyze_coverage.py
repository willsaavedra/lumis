"""Node 5: Analyze observability coverage using Claude."""
from __future__ import annotations

import asyncio
import json
import re
import time
import structlog

from apps.agent.core.config import settings
from apps.agent.nodes.base import (
    publish_progress, publish_llm_call_started, log_llm_call,
    publish_thought, publish_finding, publish_file_status, publish_cost_update,
)
from apps.agent.nodes.instrumentation_hints import (
    constraint_section,
    add_instrumentation_suggestion,
    span_start_snippet,
    error_path_suggestion as _instr_error_suggestion,
)
from apps.agent.schemas import AgentState, Finding

log = structlog.get_logger(__name__)

# Increment when the coverage prompt changes so A/B analysis is possible
PROMPT_VERSION = "coverage-v2.0"

HEURISTIC_CRITICAL_PATTERNS = [
    ("handler", "No span on HTTP/gRPC handler", "traces", "coverage"),
    ("db_call", "Database call without tracing span", "traces", "coverage"),
    ("queue", "Message queue operation without W3C trace context", "traces", "pipeline"),
]

# Framework detection patterns — used to give Claude better context
_FRAMEWORK_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "python": [
        (r"from fastapi|import fastapi", "FastAPI"),
        (r"from flask|import flask", "Flask"),
        (r"from django|import django", "Django"),
        (r"from celery|import celery", "Celery"),
    ],
    "go": [
        (r'"github\.com/gin-gonic/gin"', "Gin"),
        (r'"net/http"', "net/http"),
        (r'"github\.com/labstack/echo"', "Echo"),
    ],
    "typescript": [
        (r"from ['\"]express['\"]|require\(['\"]express", "Express"),
        (r"from ['\"]@nestjs", "NestJS"),
        (r"from ['\"]fastify", "Fastify"),
    ],
    "java": [
        (r"import org\.springframework", "Spring"),
        (r"import jakarta\.ws\.rs|javax\.ws\.rs", "JAX-RS"),
    ],
}

# Language-specific detection hints injected into the prompt
_LANG_DETECTION_HINTS: dict[str, list[str]] = {
    "go": [
        "→ Check: context.Context passed to function but NOT forwarded to all callees (lost trace context)",
        "→ Check: `go func()` launching goroutines WITHOUT propagating context (orphan goroutine — trace broken)",
        "→ Check: `if err != nil { return err }` on critical paths WITHOUT span.RecordError() or structured log",
        "→ Check: HTTP handler that reads `r.Context()` but never calls `tracer.Start(ctx, ...)`",
    ],
    "python": [
        "→ Check: `except Exception:` or bare `except:` WITHOUT span.record_exception() / logger.error(exc_info=True)",
        "→ Check: `asyncio.create_task()` WITHOUT propagating the current OTel context (context.copy_context())",
        "→ Check: Celery task decorated with @task but NOT extracting W3C traceparent from task headers",
        "→ Check: FastAPI/Flask endpoint handler that never calls tracer.start_as_current_span()",
    ],
    "javascript": [
        "→ Check: `.catch(err => ...)` WITHOUT activeSpan.recordException(err) / logger.error()",
        "→ Check: `setTimeout` / `setInterval` callbacks WITHOUT context.with() to propagate active context",
        "→ Check: `new Promise()` executor WITHOUT propagating the OTel context inside the constructor",
        "→ Check: Express/Fastify route handler that never sets span attributes (http.method, http.route)",
    ],
    "typescript": [
        "→ Check: `.catch(err => ...)` WITHOUT activeSpan.recordException(err) / logger.error()",
        "→ Check: `async` function with `await` calls that lose the active span across await boundaries",
        "→ Check: NestJS @Controller method without `@Span()` decorator or manual tracer.startActiveSpan()",
    ],
    "java": [
        "→ Check: `@Async` method WITHOUT MDC propagation (trace context lost in thread pool)",
        "→ Check: `CompletableFuture.supplyAsync()` WITHOUT explicitly passing the current Context",
        "→ Check: Spring @Service method performing DB calls without an active span wrapping the call",
    ],
    "terraform": [
        "→ Check: Hardcoded resource IDs, VPC IDs, subnet IDs, account IDs — use var.x or data sources",
        "→ Check: Missing environment isolation — same resource IDs across dev/staging/prod (use workspaces or var files)",
        "→ Check: Secrets, API keys, or credentials hardcoded in .tf files — use AWS SSM/Secrets Manager or HashiCorp Vault",
        "→ Check: Missing required_providers version constraints (use `~> x.y` to pin minor version)",
        "→ Check: No remote backend configured — state stored locally risks drift and collaboration issues",
        "→ Check: Missing variable validation blocks on critical inputs (vpc_id, instance_type, etc.)",
        "→ Check: resource_group/namespace/tags missing required organizational tags (env, team, project)",
    ],
    "hcl": [
        "→ Check: Hardcoded identifiers that prevent reuse across environments — use variables or locals",
        "→ Check: Missing variable descriptions or types — reduces module usability",
        "→ Check: No outputs defined — prevents consumers from referencing provisioned resource attributes",
    ],
    "helm": [
        "→ Check: Hardcoded image tags (use .Values.image.tag variable)",
        "→ Check: Resource limits not set — pods can starve cluster nodes",
        "→ Check: No liveness/readiness probes — cluster cannot detect unhealthy pods",
        "→ Check: Secrets stored in values.yaml — use external-secrets or sealed-secrets",
    ],
}

# Span/tracer presence patterns used for coverage map annotation
_SPAN_PATTERNS: list[str] = [
    r"tracer\.start",
    r"span\s*=",
    r"StartSpan",
    r"start_as_current_span",
    r"startActiveSpan",
    r"opentelemetry\.trace",
    r"ddtrace\.tracer",
    r"dd\.trace",
    r"tracer\.trace\(",
]

# Per-type limits for the coverage analysis node
_COVERAGE_CONFIG: dict[str, dict] = {
    # quick: user-selected scope only — many files in small LLM batches, triage model
    "quick":      {"file_limit": 120, "content_chars": 2200, "use_primary_model": False, "batch_size": 4},
    # full: PR-style breadth cap
    "full":       {"file_limit": 12,  "content_chars": 3000, "use_primary_model": True, "batch_size": 5},
    # repository: deep scan — high file cap, batched LLM calls
    "repository": {"file_limit": 2500, "content_chars": 3500, "use_primary_model": True, "batch_size": 5},
}


def _detect_framework(content: str, language: str) -> str | None:
    """Return detected web/worker framework from file content."""
    patterns = _FRAMEWORK_PATTERNS.get(language, [])
    for pattern, name in patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return name
    return None


def _has_span(content: str) -> bool:
    """Return True if file content contains any span/tracer usage pattern."""
    return any(re.search(p, content, re.IGNORECASE) for p in _SPAN_PATTERNS)


def _build_coverage_map(
    nodes: dict,
    file_obs_imports: dict[str, str],
    file_contents: dict[str, str],
) -> dict[str, dict]:
    """
    Annotate each call graph node with observability coverage status.

    Status values (per paper spec):
      present  — file imports an obs lib AND uses span/tracer references
      partial  — file imports an obs lib but has NO span references in this specific node's window
      missing  — no obs library import detected in the file at all
    """
    coverage: dict[str, dict] = {}
    for node_key, node_data in nodes.items():
        fp = node_data.get("file_path", "")
        obs = file_obs_imports.get(fp, "none")
        content = file_contents.get(fp, "")

        if obs == "none":
            status = "missing"
        elif _has_span(content):
            status = "present"
        else:
            status = "partial"

        coverage[node_key] = {
            "name": node_data.get("name"),
            "file_path": fp,
            "node_type": node_data.get("node_type"),
            "obs_import": obs,
            "status": status,
        }
    return coverage


_IAC_FILE_EXTENSIONS = frozenset({
    ".tf", ".hcl", ".bicep", ".json",   # Terraform / HCL / ARM
    ".yaml", ".yml",                    # Helm / Kubernetes manifests
    ".ts",                              # Pulumi TypeScript — but Pulumi files use infra patterns
})

_IAC_LANGUAGES_SET = frozenset({"terraform", "hcl", "bicep", "helm", "pulumi", "jsonnet", "cloudformation"})


def _is_iac_file(file_path: str, language: str | None) -> bool:
    """True when the file is part of an IaC codebase, not application code."""
    ext = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    lang = (language or "").lower()
    return lang in _IAC_LANGUAGES_SET or (ext in _IAC_FILE_EXTENSIONS and lang not in {"typescript", "javascript", "python", "go", "java", "ruby"})


def _iac_constraint_section(repo_type: str | None, iac_provider: str | None, languages: list | None) -> str:
    """Return a hard constraint for IaC repos that prevents OTel/SDK suggestions."""
    langs = [l.lower() for l in (languages or [])]
    is_iac = (
        (repo_type or "").strip().lower() == "iac"
        or bool(iac_provider)
        or any(l in _IAC_LANGUAGES_SET for l in langs)
    )
    if not is_iac:
        return ""
    provider = iac_provider or (langs[0] if langs else "Terraform")
    return (
        f"\n\n## IaC REPOSITORY CONSTRAINT — NON-NEGOTIABLE\n"
        f"This is an **Infrastructure-as-Code repository** ({provider}).\n"
        "Files contain infrastructure configuration (HCL/Terraform/YAML), NOT application source code.\n\n"
        "ALL findings and suggestions MUST be infrastructure-native:\n"
        "  • Terraform/HCL → use `variable`, `locals`, `data` sources, `terraform.workspace`\n"
        "  • Helm/YAML → use `.Values.*` references and Helm templating\n"
        "  • Bicep/ARM → use `param` declarations and `resource` data references\n\n"
        "NEVER suggest adding:\n"
        "  ✗ Python `from opentelemetry import trace` or any application SDK import\n"
        "  ✗ Node.js / JavaScript / TypeScript instrumentation code\n"
        "  ✗ dd-trace, ddtrace, datadog-lambda, or any Datadog APM tracer\n"
        "  ✗ Any code that belongs in an application runtime (not an infra config file)\n\n"
        "For hardcoded values → suggest Terraform variables, data sources, or SSM parameter lookups.\n"
        "For missing monitoring → suggest Prometheus/Datadog monitoring resources (Terraform modules, Helm chart values).\n"
        "For security gaps → suggest IAM policies, secret manager references, or encryption settings."
    )


_APP_SDK_PATTERN = re.compile(
    r"opentelemetry|ddtrace|dd-trace|dd\.tracer|datadog\.tracer"
    r"|opentracing|opencensus|openmetrics"
    r"|prometheus_client|prom-client|prom\.NewCounter"
    r"|statsd\."
    r"|go\.opentelemetry\.io|gopkg\.in/DataDog/dd-trace-go"
    r"|io\.opentelemetry|io\.opentracing"
    r"|@opentelemetry/|datadog-lambda"
    r"|micrometer|otel\.trace"
    r"|tracer\.start_as_current_span|tracer\.startActiveSpan",
    re.IGNORECASE,
)

_INFRA_AGENT_PATTERN = re.compile(
    r"datadog[/_-]agent|datadog/agent:"
    r"|otel[/_-]collector|opentelemetry[/_-]collector"
    r"|otelcol|otelcontribcol"
    # Prometheus / kube-prometheus stack
    r"|prometheus[/_-]operator|kube[/_-]prometheus"
    r"|kube[_-]state[_-]metrics|kube_state_metrics"
    r"|node[_-]exporter|nodeexporter"
    r"|alertmanager"
    r"|prometheus-community/helm-charts"
    r"|prometheus\.io/scrape"
    # Grafana Agent / Mimir / Thanos / VictoriaMetrics
    r"|grafana[/_-]agent|grafana/agent:"
    r"|victoria[_-]metrics|victoriametrics"
    r"|thanos"
    # Fluent Bit / Fluentd log shippers
    r"|fluent[/_-]bit|fluentd",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Dependency manifests — probe these files for SDK imports in the cloned repo
# ---------------------------------------------------------------------------
_DEPENDENCY_FILES: list[str] = [
    # Python
    "requirements.txt", "requirements-dev.txt", "requirements/base.txt",
    "requirements/production.txt", "pyproject.toml", "setup.py", "setup.cfg",
    "Pipfile",
    # Node / TypeScript
    "package.json", "package-lock.json",
    # Go
    "go.mod",
    # JVM
    "pom.xml", "build.gradle", "build.gradle.kts",
    # Ruby
    "Gemfile",
    # .NET
    "*.csproj",
    # Rust
    "Cargo.toml",
]

# Well-known instrumentation/telemetry bootstrap files
_INSTRUMENTATION_FILE_NAMES: frozenset[str] = frozenset({
    # Python
    "tracer.py", "tracing.py", "telemetry.py", "instrumentation.py",
    "otel.py", "observability.py", "monitoring.py", "metrics.py",
    # TypeScript / JS
    "tracer.ts", "tracing.ts", "instrumentation.ts", "otel.ts",
    "telemetry.ts", "tracer.js", "tracing.js", "instrumentation.js",
    # Go
    "tracer.go", "tracing.go", "telemetry.go", "instrumentation.go",
    "otel.go", "observability.go",
    # Java
    "TracerConfig.java", "TelemetryConfig.java", "InstrumentationConfig.java",
    "OtelConfig.java", "TracingConfig.java",
})

_MAX_PROBE_BYTES = 8000  # per file


def _probe_repo_instrumentation(repo_path: str) -> dict:
    """
    Scan the cloned repository for evidence of observability SDKs or agents
    beyond the files in the PR diff.

    Strategy:
      1. Read well-known dependency manifests (requirements.txt, go.mod,
         package.json, pom.xml …) — SDK presence in deps means the app is
         already instrumented even if the changed files don't import it.
      2. Read well-known instrumentation bootstrap files (tracer.py,
         tracing.ts, otel.go …) — these set up the SDK globally and are
         rarely changed.

    Returns: {has_app_sdk, has_infra_agent, sources: list[str]}
    """
    from pathlib import Path

    repo = Path(repo_path)
    if not repo.is_dir():
        return {"has_app_sdk": False, "has_infra_agent": False, "sources": []}

    sources: list[str] = []
    has_app_sdk = False
    has_infra_agent = False

    def _check(content: str, path: str) -> None:
        nonlocal has_app_sdk, has_infra_agent
        if not has_app_sdk and _APP_SDK_PATTERN.search(content):
            has_app_sdk = True
            sources.append(path)
        if not has_infra_agent and _INFRA_AGENT_PATTERN.search(content):
            has_infra_agent = True
            sources.append(path)

    # 1. Probe dependency manifests (exact name match at repo root or one level deep)
    for dep_name in _DEPENDENCY_FILES:
        if "*" in dep_name:
            # Glob pattern (e.g. *.csproj) — only at root
            for p in list(repo.glob(dep_name))[:3]:
                try:
                    _check(p.read_text(encoding="utf-8", errors="replace")[:_MAX_PROBE_BYTES], str(p.relative_to(repo)))
                except Exception:
                    pass
        else:
            for candidate in [repo / dep_name, *list((repo / "src").glob(dep_name) if (repo / "src").is_dir() else [])]:
                if candidate.is_file():
                    try:
                        _check(candidate.read_text(encoding="utf-8", errors="replace")[:_MAX_PROBE_BYTES],
                               str(candidate.relative_to(repo)))
                    except Exception:
                        pass
                    break  # only first match per dep file

    # 2. Probe well-known instrumentation setup files (walk entire tree, stop early)
    skip_dirs = {".git", "__pycache__", "node_modules", ".terraform", "vendor", "dist", "build", ".venv", "venv"}
    found = 0
    for p in repo.rglob("*"):
        if found >= 20:  # stop after finding 20 such files — avoid scanning huge repos
            break
        if not p.is_file():
            continue
        if any(s in p.parts for s in skip_dirs):
            continue
        if p.name in _INSTRUMENTATION_FILE_NAMES:
            found += 1
            try:
                _check(p.read_text(encoding="utf-8", errors="replace")[:_MAX_PROBE_BYTES],
                       str(p.relative_to(repo)))
            except Exception:
                pass

    return {"has_app_sdk": has_app_sdk, "has_infra_agent": has_infra_agent, "sources": sources}


def _check_instrumentation_presence(state: AgentState) -> dict:
    """
    Determine whether the repository has any observable instrumentation.

    Priority order:
      1. Explicit user setting on repo.instrumentation (trust it unconditionally)
      2. Scan content of changed files in the PR diff
      3. Probe the cloned repo: dependency manifests + well-known setup files

    Returns: {has_any, has_app_sdk, has_infra_agent, source}
    """
    repo_context = state.get("repo_context") or {}
    instrumentation = (repo_context.get("instrumentation") or "").strip().lower()

    # Explicit user-provided setting takes priority
    if instrumentation and instrumentation != "none":
        return {"has_any": True, "has_app_sdk": True, "has_infra_agent": False, "source": "explicit"}
    if instrumentation == "none":
        return {"has_any": False, "has_app_sdk": False, "has_infra_agent": False, "source": "explicit_none"}

    # Scan analyzed file contents (PR diff)
    combined = "\n".join(
        f.get("content") or "" for f in (state.get("changed_files") or []) if f.get("content")
    )
    has_app_sdk = bool(_APP_SDK_PATTERN.search(combined))
    has_infra_agent = bool(_INFRA_AGENT_PATTERN.search(combined))

    if has_app_sdk or has_infra_agent:
        return {
            "has_any": True,
            "has_app_sdk": has_app_sdk,
            "has_infra_agent": has_infra_agent,
            "source": "diff_scan",
        }

    # Probe the cloned repo for SDK/agent evidence outside the changed files
    repo_path = state.get("repo_path")
    if repo_path:
        probe = _probe_repo_instrumentation(repo_path)
        if probe["has_app_sdk"] or probe["has_infra_agent"]:
            log.info(
                "instrumentation_detected_via_probe",
                job_id=state.get("job_id"),
                sources=probe["sources"][:5],
            )
            return {
                "has_any": True,
                "has_app_sdk": probe["has_app_sdk"],
                "has_infra_agent": probe["has_infra_agent"],
                "source": "repo_probe",
            }

    return {
        "has_any": False,
        "has_app_sdk": False,
        "has_infra_agent": False,
        "source": "none",
    }


async def _persist_instrumentation_detection(job_id: str, tenant_id: str, vendor: str) -> None:
    """
    Best-effort: update repo.instrumentation when the probe discovers an SDK
    that wasn't recorded in the DB. Keeps future analyses from re-probing.
    """
    if not job_id or not tenant_id:
        return
    try:
        import uuid
        from sqlalchemy import select
        from apps.api.core.database import get_session_with_tenant
        from apps.api.models.analysis import AnalysisJob
        from apps.api.models.scm import Repository

        async with get_session_with_tenant(tenant_id) as session:
            job_res = await session.execute(select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)))
            job = job_res.scalar_one_or_none()
            if not job:
                return
            repo_res = await session.execute(select(Repository).where(Repository.id == job.repo_id))
            repo = repo_res.scalar_one_or_none()
            if repo and not repo.instrumentation:
                repo.instrumentation = vendor
                log.info("instrumentation_persisted_from_probe", job_id=job_id, vendor=vendor)
    except Exception as exc:
        log.warning("instrumentation_persist_failed", job_id=job_id, error=str(exc))


async def analyze_coverage_node(state: AgentState) -> dict:
    """
    Analyze observability coverage.
    Respects analysis_type:
      - quick:      user-selected files only, triage model, batched, no heuristics (no call graph)
      - full:       capped breadth, primary model, heuristics from call graph
      - repository: large prioritized file set, batched, primary model, heuristics
    """
    analysis_type = state.get("request", {}).get("analysis_type", "full")
    cfg = _COVERAGE_CONFIG.get(analysis_type, _COVERAGE_CONFIG["full"])

    await publish_progress(state, "analyzing", 50, "Analyzing observability coverage...", stage_index=5)

    call_graph = state.get("call_graph") or {}
    nodes = call_graph.get("nodes", {})
    file_obs_imports: dict[str, str] = call_graph.get("file_obs_imports", {})
    findings: list[dict] = list(state.get("findings", []))

    # Build a map of file path → content for coverage annotation
    file_contents: dict[str, str] = {
        f["path"]: (f.get("content") or "")
        for f in state.get("changed_files", [])
        if f.get("path")
    }

    # Build coverage map (Phase 2: annotate before LLM)
    coverage_map: dict[str, dict] = {}
    if nodes:
        coverage_map = _build_coverage_map(nodes, file_obs_imports, file_contents)

    # Extract instrumentation context once — used by heuristic suggestions below
    _hctx        = state.get("repo_context") or state.get("request", {})
    _h_instr     = _hctx.get("instrumentation")
    _h_obs_back  = _hctx.get("observability_backend")
    _h_language  = _hctx.get("language")
    _h_lang_str  = (
        _h_language[0] if isinstance(_h_language, list) and _h_language else (_h_language or "")
    )

    # Detect IaC repo early — heuristic span/trace patterns don't apply to infra code
    _hctx_early = state.get("repo_context") or state.get("request", {})
    _is_iac_repo_early = (
        (_hctx_early.get("repo_type") or "").strip().lower() == "iac"
        or bool(_hctx_early.get("iac_provider"))
        or any(
            (l or "").lower() in _IAC_LANGUAGES_SET
            for l in ((_hctx_early.get("language") or []) if isinstance(_hctx_early.get("language"), list) else [_hctx_early.get("language")])
        )
    )

    # Heuristic analysis from call graph — only available when parse_ast ran (full / repository)
    # IaC repos don't use app SDK patterns — skip heuristic span/trace checks entirely
    if nodes and not _is_iac_repo_early:
        for node_key, node in nodes.items():
            node_type = node.get("node_type", "utility")
            file_path = node.get("file_path", "")
            line = node.get("line", 0)

            for required_type, title, pillar, dimension in HEURISTIC_CRITICAL_PATTERNS:
                if node_type == required_type:
                    # Only add heuristic finding if coverage map confirms gap
                    cov_status = coverage_map.get(node_key, {}).get("status", "missing")
                    if cov_status == "present":
                        continue  # file already has span instrumentation — skip

                    # Generate an instrumentation-aware suggestion
                    _h_suggestion = span_start_snippet(
                        lang=_h_lang_str,
                        operation=node.get("name", "operation"),
                        instrumentation=_h_instr,
                    )
                    findings.append({
                        "pillar": pillar,
                        "severity": "critical",
                        "dimension": dimension,
                        "title": title,
                        "description": (
                            f"The function `{node['name']}` in `{file_path}` "
                            f"is a {node_type} but has no observability instrumentation."
                        ),
                        "file_path": file_path,
                        "line_start": line,
                        "line_end": line + 10,
                        "suggestion": _h_suggestion,
                        "estimated_monthly_cost_impact": 0.0,
                        "confidence": "high",
                    })

    # ------------------------------------------------------------------
    # Instrumentation gate: if no SDK or agent is present, emit critical
    # findings for metrics and traces. These pillars are meaningless without
    # active instrumentation — app metrics need an SDK (OTEL / ddtrace /
    # Prometheus), traces need an SDK, infra metrics need an agent.
    # ------------------------------------------------------------------
    _gate_instr = _check_instrumentation_presence(state)

    # When the probe detected instrumentation that the repo_context didn't know about,
    # persist the discovery to the DB and update the in-memory context so downstream
    # nodes (generate_suggestions) see the correct instrumentation vendor.
    _repo_context_update: dict = {}
    if _gate_instr["source"] == "repo_probe":
        _detected_vendor = "otel" if _gate_instr.get("has_app_sdk") else "other"
        _repo_context_update = {"instrumentation": _detected_vendor}
        # Merge into current state repo_context for downstream nodes
        _cur_ctx = dict(state.get("repo_context") or {})
        _cur_ctx["instrumentation"] = _detected_vendor
        state = {**state, "repo_context": _cur_ctx}  # type: ignore[assignment]
        # Best-effort async DB persist — failure must not block the pipeline
        asyncio.ensure_future(
            _persist_instrumentation_detection(
                state.get("job_id", ""),
                state.get("tenant_id", ""),
                _detected_vendor,
            )
        )
    if not _gate_instr["has_any"]:
        _ctx_for_noninstr = state.get("repo_context") or state.get("request", {})
        _obs_backend_ni   = _ctx_for_noninstr.get("observability_backend")
        _language_ni      = _ctx_for_noninstr.get("language")
        _repo_type_ni     = _ctx_for_noninstr.get("repo_type")
        _iac_provider_ni  = _ctx_for_noninstr.get("iac_provider")
        _ctx_summary_ni   = _ctx_for_noninstr.get("context_summary")
        _primary_lang     = (
            _language_ni[0] if isinstance(_language_ni, list) and _language_ni else _language_ni
        )
        _is_iac_repo = (
            (_repo_type_ni or "").strip().lower() == "iac"
            or bool(_iac_provider_ni)
            or (_primary_lang or "").strip().lower() in {"terraform", "hcl", "helm", "bicep", "pulumi"}
        )
        _no_instr_detail = (
            "No observability monitoring was detected in this infrastructure repository. "
            "IaC repos provision resources that need infrastructure-level monitoring agents or exporters:\n"
            "• Kubernetes clusters: kube-prometheus stack (Prometheus Operator + kube-state-metrics + node-exporter)\n"
            "• Datadog shops: Datadog Agent via Datadog Operator or DaemonSet\n"
            "• General infra: Prometheus node-exporter, cloud-provider exporters\n\n"
            "No application SDK is needed — monitoring is added at the infrastructure layer."
        ) if _is_iac_repo else (
            "No observability instrumentation was detected in this repository. "
            "Application metrics (RED method) and distributed traces require an active "
            "SDK or agent:\n"
            "• App SDKs: OpenTelemetry SDK, Datadog APM (ddtrace), OpenTracing, "
            "Prometheus client, OpenMetrics\n"
            "• Infra agents: Datadog Agent, OpenTelemetry Collector\n\n"
            "Without instrumentation, it is impossible to emit metrics or traces. "
            "Add an SDK or agent before expecting observability coverage."
        )
        _no_instr_suggestion = add_instrumentation_suggestion(
            instrumentation=None,
            obs_backend=_obs_backend_ni,
            language=_primary_lang,
            repo_type=_repo_type_ni,
            iac_provider=_iac_provider_ni,
            context_summary=_ctx_summary_ni,
        )
        for _pillar in ("metrics", "traces"):
            findings.append({
                "pillar": _pillar,
                "severity": "critical",
                "dimension": "coverage",
                "title": f"No instrumentation detected — {_pillar} unavailable",
                "description": _no_instr_detail,
                "file_path": None,
                "line_start": None,
                "line_end": None,
                "suggestion": _no_instr_suggestion,
                "estimated_monthly_cost_impact": 0.0,
                "confidence": "high",
                "is_no_instrumentation": True,
            })
        log.warning(
            "no_instrumentation_findings_added",
            job_id=state.get("job_id"),
            source=_gate_instr["source"],
        )

    # ------------------------------------------------------------------
    # LLM semantic analysis — token-aware batching + parallel execution
    # ------------------------------------------------------------------
    from apps.agent.llm.token_budget import compute_batches, estimate_tokens
    from apps.agent.llm.file_chunker import chunk_file
    from apps.agent.llm.batch_runner import BatchRunner
    from apps.agent.manifest import AnalysisManifest

    min_score = 2 if analysis_type == "quick" else 1
    relevant_files = [
        f for f in state["changed_files"]
        if f["relevance_score"] >= min_score and f.get("content")
    ]

    file_limit = cfg["file_limit"]
    content_chars = cfg["content_chars"]
    capped = relevant_files[:file_limit]

    manifest = AnalysisManifest(capped)

    if capped:
        # Resolve the model name for budget calculation
        provider = state.get("request", {}).get("llm_provider", "anthropic")
        if provider == "cerebra_ai":
            _model = settings.cerebra_ai_model_primary if cfg["use_primary_model"] else settings.cerebra_ai_model_triage
        else:
            _model = settings.anthropic_model_primary if cfg["use_primary_model"] else settings.anthropic_model_triage

        call_graph_tokens = estimate_tokens(
            json.dumps(state.get("call_graph") or {})[:6000]
        )

        batch_plan = compute_batches(capped, _model, call_graph_tokens)

        # Chunk oversized files and add them as additional batches
        for oversized in batch_plan.oversized_files:
            chunks = chunk_file(oversized, batch_plan.budget_per_batch)
            manifest.mark_chunked(oversized.get("path", ""), len(chunks))
            for chunk in chunks:
                batch_plan.batches.append([chunk])

        manifest.total_batches = len(batch_plan.batches)
        all_batches = batch_plan.batches

        # Mark all files in manifest
        for batch_idx, batch in enumerate(all_batches):
            for f in batch:
                manifest.mark_batched(f.get("path", ""), batch_idx)

        # Shared state captured for the analyze function
        _state = state
        _content_chars = content_chars
        _use_primary = cfg["use_primary_model"]
        _cov_map = coverage_map
        _file_obs = file_obs_imports
        _all_batch_paths = [
            [f.get("path", "") for f in batch]
            for batch in all_batches
        ]

        files_done_counter = {"count": 0}

        async def _analyze_batch(batch: list[dict]) -> list[dict]:
            """Wrapper that calls the existing LLM analysis function."""
            for b in batch:
                await publish_file_status(_state, b["path"], "scanning", b.get("language") or "")
                manifest.mark_analyzing(b.get("path", ""))

            return await _llm_analyze_coverage(
                batch,
                _state,
                content_chars=_content_chars,
                use_primary_model=_use_primary,
                coverage_map=_cov_map,
                file_obs_imports=_file_obs,
            )

        async def _on_batch_complete(result) -> None:
            """Callback fired after each batch — updates manifest + SSE."""
            batch_files = result.files
            batch_findings = result.findings

            if result.error:
                for b in batch_files:
                    manifest.mark_failed(b.get("path", ""), result.error)
                    await publish_file_status(_state, b["path"], "done", b.get("language") or "")
                manifest.record_retry()
                log.warning(
                    "llm_coverage_analysis_failed",
                    error=result.error,
                    batch_size=len(batch_files),
                    job_id=_state.get("job_id"),
                )
                return

            # Process findings
            accepted = 0
            rejected = 0
            files_with_findings: set[str] = set()
            for f in batch_findings:
                if f.get("confidence", "medium") != "low":
                    findings.append(f)
                    accepted += 1
                    files_with_findings.add(f.get("file_path", ""))
                    await publish_finding(_state, f, "analyze_coverage")
                else:
                    rejected += 1

            # Update manifest for each file in the batch
            for b in batch_files:
                path = b.get("path", "")
                file_finding_count = sum(
                    1 for f in batch_findings
                    if f.get("file_path") == path and f.get("confidence", "medium") != "low"
                )
                manifest.mark_completed(path, file_finding_count)
                await publish_file_status(_state, path, "done", b.get("language") or "")

            files_done_counter["count"] += len(batch_files)
            files_done = files_done_counter["count"]

            pct = 50 + int((files_done / len(capped)) * 10) if capped else 55
            await publish_progress(
                _state, "analyzing", min(pct, 59),
                f"Batch {result.batch_index + 1}/{len(all_batches)} — {accepted} findings",
                stage_index=5, files_analyzed=files_done, files_total=len(capped),
            )
            await publish_thought(
                _state, "analyze_coverage",
                f"Analyzed batch {result.batch_index + 1} ({len(batch_files)} files): "
                f"{accepted} findings accepted, {rejected} filtered",
                status="active" if files_done < len(capped) else "done",
                files=[b.get("path", "") for b in batch_files],
            )
            await publish_cost_update(_state, node="analyze_coverage")

            log.info(
                "coverage_batch_result",
                batch_index=result.batch_index,
                files_in_batch=len(batch_files),
                findings_accepted=accepted,
                findings_rejected=rejected,
                job_id=_state.get("job_id"),
            )

        # Execute all batches with parallel runner
        runner = BatchRunner(
            max_concurrent=settings.max_concurrent_batches,
            max_retries=3,
        )
        await runner.run_all(all_batches, _analyze_batch, _on_batch_complete)

        # Output validation: re-analyze files stuck in non-terminal state
        # (LLM output may have been truncated, omitting some files)
        stuck_files = [
            f for f in capped
            if manifest._files.get(f.get("path", ""), None)
            and manifest._files[f["path"]].status not in ("completed", "failed", "skipped_triage")
        ]
        if stuck_files:
            log.warning(
                "output_validation_reanalysis",
                stuck_count=len(stuck_files),
                paths=[f["path"] for f in stuck_files[:10]],
                job_id=state.get("job_id"),
            )
            # Re-analyze in small batches of 2 files
            for i in range(0, len(stuck_files), 2):
                mini_batch = stuck_files[i:i + 2]
                try:
                    retry_findings = await _analyze_batch(mini_batch)
                    from apps.agent.llm.batch_runner import BatchResult
                    await _on_batch_complete(BatchResult(
                        batch_index=len(all_batches) + i,
                        files=mini_batch,
                        findings=retry_findings,
                    ))
                except Exception as e:
                    for mb in mini_batch:
                        manifest.mark_failed(mb.get("path", ""), f"reanalysis_failed: {e}")

        # Completeness guarantee — mark silently skipped files as failed
        manifest.assert_complete()

        log.info(
            "coverage_manifest",
            coverage_pct=manifest.coverage_pct,
            eligible=manifest.eligible_count,
            completed=manifest.completed_count,
            failed=len(manifest.failed_files),
            job_id=state.get("job_id"),
        )

    await publish_progress(
        state, "analyzing", 60, f"Found {len(findings)} initial findings.",
        stage_index=5, files_analyzed=len(capped),
    )
    return {
        "findings": findings,
        "coverage_map": coverage_map,
        "analysis_manifest": manifest.to_completeness_report() if capped else None,
    }


async def _llm_analyze_coverage(
    files: list[dict],
    state: AgentState,
    content_chars: int = 3000,
    use_primary_model: bool = True,
    coverage_map: dict | None = None,
    file_obs_imports: dict | None = None,
) -> list[dict]:
    """
    Use Claude to analyze files for semantic observability gaps.

    Prompt version: PROMPT_VERSION (coverage-v2.0)
    Improvements over v1.0:
      - Mandatory Q1-Q4 reasoning framework before reporting any finding
      - NEVER REPORT section with negative few-shot examples to reduce FP rate
      - Language-specific detection hints per file language
      - Coverage map JSON passed as structured input (Phase 2)
      - Calls log_llm_call for quality tracking

    use_primary_model=True  → settings.anthropic_model_primary (Sonnet)
    use_primary_model=False → settings.anthropic_model_triage  (Haiku)
    """
    from apps.agent.llm.chat_completion import chat_complete

    provider = state.get("request", {}).get("llm_provider", "anthropic")
    if provider == "cerebra_ai":
        model = settings.cerebra_ai_model_primary if use_primary_model else settings.cerebra_ai_model_triage
    else:
        model = settings.anthropic_model_primary if use_primary_model else settings.anthropic_model_triage

    log.info(
        "coverage_batch_decision",
        provider=provider,
        model=model,
        files_in_batch=len(files),
        use_primary_model=use_primary_model,
        job_id=state.get("job_id"),
    )

    # Build file summaries
    detected_langs: set[str] = set()
    file_summaries = []
    for f in files:
        content = (f.get("content") or "")[:content_chars]
        lang = f.get("language", "")
        if lang:
            detected_langs.add(lang)
        framework = _detect_framework(content, lang) if lang else None
        obs_import = (file_obs_imports or {}).get(f["path"], "unknown")
        header = f"File: {f['path']} | Language: {lang} | Obs-imports: {obs_import}"
        if framework:
            header += f" | Framework: {framework}"
        if f.get("_is_chunk"):
            header += f" | CHUNK {f['_chunk_index'] + 1}/{f['_chunk_total']} (analyze only functions shown in full)"
        file_summaries.append(f"{header}\n```{lang}\n{content}\n```")

    files_text = "\n\n".join(file_summaries)

    # Coverage map as JSON — gives Claude structured input about what's already instrumented
    coverage_json = ""
    if coverage_map:
        relevant_nodes = {
            k: {"name": v["name"], "type": v["node_type"], "status": v["status"]}
            for k, v in coverage_map.items()
            if v.get("node_type") in ("handler", "db_call", "http_client", "queue")
        }
        if relevant_nodes:
            coverage_json = f"\n\nCall graph coverage map (annotated):\n```json\n{json.dumps(relevant_nodes, indent=2)}\n```"

    # Datadog / obs backend context
    dd_context = ""
    if state.get("dd_coverage"):
        existing = state["dd_coverage"].get("metrics", [])
        dd_context = f"\nAlready-instrumented Datadog metrics: {', '.join(existing[:20]) or 'none'}"

    ctx = state.get("repo_context") or state.get("request", {})
    repo_type = ctx.get("repo_type")
    app_subtype = ctx.get("app_subtype")
    iac_provider = ctx.get("iac_provider")
    language = ctx.get("language")
    obs_backend = ctx.get("observability_backend")
    instrumentation = ctx.get("instrumentation")
    obs_metadata = ctx.get("obs_metadata") or {}
    context_summary = ctx.get("context_summary")

    _INSTRUMENTATION_LABELS = {
        "otel": "OpenTelemetry SDK (vendor-neutral)",
        "datadog": "Datadog tracer / dd-trace (proprietary)",
        "mixed": "Mixed — both OpenTelemetry and Datadog instrumentation present",
        "none": "No instrumentation library detected",
        "other": "Other instrumentation library",
    }

    context_header = ""
    if repo_type:
        type_label = repo_type
        if repo_type == "app" and app_subtype:
            type_label = f"app ({app_subtype})"
        elif repo_type == "iac" and iac_provider:
            type_label = f"iac ({iac_provider})"
        context_header += f"\nRepository type: {type_label}"
    if language:
        langs = language if isinstance(language, list) else [language]
        context_header += f"\nPrimary language(s): {', '.join(langs)}"
    if instrumentation:
        label = _INSTRUMENTATION_LABELS.get(instrumentation, instrumentation)
        context_header += f"\nInstrumentation library: {label}"
        if instrumentation == "otel":
            context_header += (
                "\n  → Flag gaps where OTEL spans/metrics/logs are expected but missing."
                "\n  → Highlight incorrect or missing resource attributes."
            )
        elif instrumentation == "datadog":
            context_header += (
                "\n  → Flag gaps in dd-trace span coverage, missing custom metrics, and unstructured logs."
                "\n  → Note any OpenTelemetry code that conflicts with dd-trace."
            )
        elif instrumentation == "none":
            context_header += (
                "\n  → Treat this as a greenfield: recommend adding OTEL instrumentation as the baseline."
            )
        elif instrumentation == "mixed":
            context_header += (
                "\n  → Identify conflicts and duplicate instrumentation between OTEL and dd-trace."
            )
    if obs_backend:
        context_header += f"\nObservability backend / destination: {obs_backend}"
        if obs_backend == "datadog" and obs_metadata.get("tags"):
            tags_dict = obs_metadata["tags"]
            tags_str = ", ".join(f"{k}:{v}" for k, v in tags_dict.items()) if isinstance(tags_dict, dict) else str(tags_dict)
            context_header += f"\nDatadog standard tags: {tags_str}"
        elif obs_backend in ("prometheus", "grafana") and obs_metadata.get("labels"):
            labels_dict = obs_metadata["labels"]
            labels_str = ", ".join(f"{k}={v}" for k, v in labels_dict.items()) if isinstance(labels_dict, dict) else str(labels_dict)
            context_header += f"\nPrometheus/Grafana standard labels: {labels_str}"
        if obs_metadata.get("service_name"):
            context_header += f"\nService name in observability backend: {obs_metadata['service_name']}"
        if obs_metadata.get("environment"):
            context_header += f"\nEnvironment: {obs_metadata['environment']}"
    if context_summary:
        context_header += f"\n\nRepository context (from README/docs):\n{context_summary[:1500]}"

    # Language-specific detection hints for files in this batch
    lang_hints_parts: list[str] = []
    for lang in sorted(detected_langs):
        hints = _LANG_DETECTION_HINTS.get(lang, [])
        if hints:
            lang_hints_parts.append(f"[{lang.upper()}]\n" + "\n".join(hints))
    lang_hints_section = ""
    if lang_hints_parts:
        lang_hints_section = "\n\nLanguage-specific detection checklist:\n" + "\n\n".join(lang_hints_parts)

    # Inject RAG context from the knowledge base if available
    rag_context = state.get("rag_context") or ""
    rag_section = f"\n\n{rag_context}" if rag_context else ""

    # Inject call graph summary (shared across all batches — cacheable)
    cg_summary = (state.get("call_graph") or {}).get("summary", "")
    call_graph_section = f"\n\n{cg_summary}" if cg_summary else ""

    # Hard constraint: keep all suggestions aligned with the declared instrumentation / repo type
    instr_constraint = constraint_section(instrumentation, obs_backend)
    iac_constraint = _iac_constraint_section(
        repo_type,
        iac_provider,
        language if isinstance(language, list) else ([language] if language else []),
    )

    system_prompt = f"""You are an expert SRE auditing code for observability gaps (prompt version: {PROMPT_VERSION}).{rag_section}{call_graph_section}{iac_constraint}{instr_constraint}

## Mandatory Reasoning Framework
Before reporting ANY finding, internally answer all four questions:
  Q1. Does this code path handle money, user data, or a critical SLA operation?
  Q2. Where could the trace context be silently dropped (async boundaries, thread pools, goroutines)?
  Q3. Which error paths are completely blind — no span, no structured log, no metric?
  Q4. Is there high-cardinality noise or redundant instrumentation that harms signal-to-noise ratio?
Only report findings that answer Q1, Q2, or Q3 affirmatively AND Q4 negatively.

## Focus Areas
- Missing or incomplete OpenTelemetry spans on HTTP handlers, DB calls, queue consumers
- Unstructured logs that should be structured (key=value or JSON)
- Missing latency/error-rate metrics on critical paths
- Missing trace context propagation across service/async boundaries
- High-cardinality metric labels (user_id, order_id as label values)

## Confidence Calibration
- confidence="high"   → gap is unambiguous (e.g. HTTP handler with literally zero span)
- confidence="medium" → probable gap but context is partial (e.g. span may exist in a base class)
- confidence="low"    → speculative — these will be automatically FILTERED OUT

## NEVER REPORT (negative examples — these are NOT findings)
- Pure utility/helper functions with no I/O (e.g. string formatters, validators, math helpers)
- `errors.Is(err, ErrNotFound)` or `errors.As` — intentional not-found handling, NOT an error path gap
- Logging a user-facing 404/401 at DEBUG level — this is intentional noise reduction
- Internal health-check endpoints (`/healthz`, `/readyz`, `/ping`) — these should NOT be traced
- Test files (`_test.go`, `test_*.py`, `*.spec.ts`) — do not analyze test code
- Import statements, variable declarations, or struct definitions — not execution paths
- Functions named `init`, `setup`, `teardown`, `close`, `shutdown` — lifecycle, not business logic

Do NOT report missing tests, missing error handling, or style issues."""

    user_content = f"""Analyze these files for observability gaps:{context_header}{dd_context}{coverage_json}{lang_hints_section}

{files_text}

Return a JSON array of findings. Each finding MUST include ALL fields:
[{{
  "pillar": "metrics|logs|traces|iac|pipeline",
  "severity": "critical|warning|info",
  "dimension": "cost|snr|pipeline|compliance|coverage",
  "confidence": "high|medium|low",
  "title": "Short, specific title (< 60 chars)",
  "description": "What is missing and why it matters in production",
  "file_path": "path/to/file.ext",
  "line_start": 42,
  "line_end": 50,
  "estimated_monthly_cost_impact": 0.0,
  "suggestion": "Concrete fix using the correct language/paradigm for this file (Terraform vars, HCL data sources, OTel spans, etc.)",
  "code_before": "Exact problematic code extracted from the file (2-8 lines showing the actual issue)",
  "code_after": "Corrected version of the same code snippet — syntactically valid and production-ready"
}}]

CRITICAL for code_before / code_after:
- Extract the REAL lines from the file content shown above — do NOT invent placeholder code
- code_before must match what is actually in the file at line_start..line_end
- code_after must be syntactically correct for the file's language
- For Terraform (.tf): use variable/locals/data patterns — NEVER Python/JS/Go SDK code
- For Helm/YAML: use .Values.* references — NEVER application library imports
- Keep both snippets concise (2-8 lines each)

Return ONLY the JSON array — no markdown fences, no explanations."""

    await publish_llm_call_started(
        state,
        "analyze_coverage",
        model,
        detail=f"Coverage batch ({len(files)} file(s)) — model {model}",
    )
    t0 = time.monotonic()
    resp = await chat_complete(
        system=system_prompt,
        user=user_content,
        model=model,
        max_tokens=2500,
        provider=provider,
        base_url=settings.cerebra_ai_base_url,
        api_key=settings.anthropic_api_key if provider == "anthropic" else settings.cerebra_ai_api_key,
        temperature=settings.cerebra_ai_temperature if provider == "cerebra_ai" else 0.3,
        top_p=settings.cerebra_ai_top_p if provider == "cerebra_ai" else 0.9,
        timeout=settings.cerebra_ai_timeout if provider == "cerebra_ai" else 120,
    )
    latency_ms = (time.monotonic() - t0) * 1000

    findings: list[dict] = []
    try:
        raw = resp.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        findings = json.loads(raw)
    except Exception as e:
        log.warning("llm_response_parse_failed", error=str(e))

    await log_llm_call(
        state=state,
        node="analyze_coverage",
        model=model,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        latency_ms=latency_ms,
        findings_count=len(findings),
        prompt_version=PROMPT_VERSION,
        cached_tokens=getattr(resp, "cached_tokens", 0),
    )

    return findings
