"""
Shared helpers that make agent findings and suggestions consistent with
the instrumentation library declared in the repository context.

Supported values  (repo_context.instrumentation):
  otel     → OpenTelemetry SDK (vendor-neutral)
  datadog  → Datadog APM / dd-trace
  mixed    → Both OTEL and dd-trace present
  none     → No instrumentation detected
  other    → Unknown / custom library

Usage:
  from apps.agent.nodes.instrumentation_hints import (
      constraint_section,
      error_path_suggestion,
      structured_log_suggestion,
      add_instrumentation_suggestion,
      span_start_snippet,
  )
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Human-readable labels
# ---------------------------------------------------------------------------
INSTRUMENTATION_LABELS: dict[str, str] = {
    "otel":    "OpenTelemetry SDK (vendor-neutral)",
    "datadog": "Datadog APM (dd-trace / ddtrace)",
    "mixed":   "Mixed — both OpenTelemetry and Datadog present",
    "none":    "No instrumentation library detected",
    "other":   "Other instrumentation library",
}

# ---------------------------------------------------------------------------
# System-prompt constraint section
# ---------------------------------------------------------------------------

def constraint_section(instrumentation: str | None, obs_backend: str | None = None) -> str:
    """
    Return a hard constraint paragraph to inject into the system prompt.
    Forces Claude to use only the configured instrumentation in every suggestion.
    Returns an empty string when instrumentation is unknown / none.
    """
    instr = (instrumentation or "").strip().lower()

    if instr == "otel":
        return (
            "\n\n## INSTRUMENTATION CONSTRAINT — NON-NEGOTIABLE\n"
            "This repository is instrumented with **OpenTelemetry SDK**.\n"
            "ALL code suggestions MUST use only OpenTelemetry APIs "
            "(opentelemetry-* packages / go.opentelemetry.io / @opentelemetry/*).\n"
            "NEVER suggest Datadog dd-trace imports, decorators, or functions.\n"
            "If a Datadog-specific concept comes up, explain the equivalent OTEL pattern instead."
        )

    if instr == "datadog":
        return (
            "\n\n## INSTRUMENTATION CONSTRAINT — NON-NEGOTIABLE\n"
            "This repository is instrumented with **Datadog APM (dd-trace / ddtrace)**.\n"
            "ALL code suggestions MUST use only Datadog APM APIs "
            "(ddtrace / dd-trace / dd-trace-go / dd-trace-js / dd-trace-java).\n"
            "NEVER suggest OpenTelemetry SDK imports, tracers, or exporters.\n"
            "If you would normally recommend an OTEL span, translate it to the equivalent "
            "dd-trace pattern instead."
        )

    if instr == "mixed":
        return (
            "\n\n## INSTRUMENTATION CONSTRAINT\n"
            "This repository uses MIXED instrumentation (both OpenTelemetry and Datadog APM).\n"
            "• Prefer OpenTelemetry APIs for NEW instrumentation.\n"
            "• Flag any conflicts where dd-trace and OTEL interfere.\n"
            "• NEVER recommend adding a third vendor SDK.\n"
            "• Warn when the same code path is double-traced."
        )

    return ""


# ---------------------------------------------------------------------------
# Per-language, per-vendor code snippets
# ---------------------------------------------------------------------------

def error_path_suggestion(lang: str, instrumentation: str | None) -> str:
    """
    Return the correct error-recording snippet for the given language
    and instrumentation vendor.
    """
    instr = (instrumentation or "otel").strip().lower()
    use_dd = instr == "datadog"

    if lang == "go":
        if use_dd:
            return (
                'if err != nil {\n'
                '    span.SetTag(ext.Error, err)\n'
                '    span.SetTag(ext.ErrorMsg, err.Error())\n'
                '    log.Error("operation_failed", "error", err)\n'
                '    return err\n'
                '}\n'
                '// imports: "gopkg.in/DataDog/dd-trace-go.v1/ddtrace/ext"'
            )
        return (
            'if err != nil {\n'
            '    span.RecordError(err)\n'
            '    span.SetStatus(codes.Error, err.Error())\n'
            '    logger.Error("operation_failed", "error", err)\n'
            '    return err\n'
            '}\n'
            '// imports: "go.opentelemetry.io/otel/codes"'
        )

    if lang == "python":
        if use_dd:
            return (
                'except Exception as exc:\n'
                '    span.set_tag_str(ddtrace.ext.errors.ERROR_MSG, str(exc))\n'
                '    span.error = 1\n'
                '    logger.error("operation_failed", exc_info=True)\n'
                '    raise\n'
                '# import ddtrace'
            )
        return (
            'except Exception as exc:\n'
            '    span.record_exception(exc)\n'
            '    span.set_status(StatusCode.ERROR, str(exc))\n'
            '    logger.error("operation_failed", exc_info=True)\n'
            '    raise\n'
            '# from opentelemetry.trace import StatusCode'
        )

    if lang in ("javascript", "typescript"):
        if use_dd:
            return (
                '.catch((err) => {\n'
                "    span.setTag('error', true);\n"
                "    span.setTag('error.message', err.message);\n"
                "    span.setTag('error.stack', err.stack);\n"
                '    logger.error({ err }, "operation_failed");\n'
                '    throw err;\n'
                '})\n'
                "// const tracer = require('dd-trace').init();"
            )
        return (
            '.catch((err) => {\n'
            '    activeSpan.recordException(err);\n'
            '    activeSpan.setStatus({ code: SpanStatusCode.ERROR, message: err.message });\n'
            '    logger.error({ err }, "operation_failed");\n'
            '    throw err;\n'
            '})\n'
            "// import { SpanStatusCode } from '@opentelemetry/api';"
        )

    if lang == "java":
        if use_dd:
            return (
                'catch (Exception e) {\n'
                '    span.setTag(Tags.ERROR, true);\n'
                '    span.log(Map.of("error.object", e, "message", e.getMessage()));\n'
                '    log.error("operation_failed", e);\n'
                '    throw e;\n'
                '}\n'
                '// import io.opentracing.tag.Tags; (dd-trace uses OpenTracing API)'
            )
        return (
            'catch (Exception e) {\n'
            '    span.recordException(e);\n'
            '    span.setStatus(StatusCode.ERROR, e.getMessage());\n'
            '    log.error("operation_failed", e);\n'
            '    throw e;\n'
            '}\n'
            '// import io.opentelemetry.api.trace.StatusCode;'
        )

    # Fallback
    if use_dd:
        return "span.set_tag('error', True); span.error = 1  # dd-trace"
    return "span.record_exception(exc); span.set_status(StatusCode.ERROR)  # opentelemetry"


def structured_log_suggestion(lang: str, instrumentation: str | None) -> str:
    """
    Return the structured logging snippet aligned with the vendor's preferred logger
    or trace-correlation pattern.
    """
    instr = (instrumentation or "otel").strip().lower()
    use_dd = instr == "datadog"

    if lang == "go":
        if use_dd:
            return (
                '// Inject Datadog trace context into structured log fields:\n'
                'span := tracer.StartSpanFromContext(ctx, "operation")\n'
                'log.Info("event_name",\n'
                '    "dd.trace_id", span.Context().TraceID(),\n'
                '    "dd.span_id",  span.Context().SpanID(),\n'
                '    "key", value,\n'
                ')'
            )
        return (
            '// Inject OTEL trace context into structured log:\n'
            'spanCtx := trace.SpanFromContext(ctx).SpanContext()\n'
            'log.Info("event_name",\n'
            '    "trace_id", spanCtx.TraceID().String(),\n'
            '    "span_id",  spanCtx.SpanID().String(),\n'
            '    "key", value,\n'
            ')'
        )

    if lang == "python":
        if use_dd:
            return (
                '# Use structlog with Datadog trace injection:\n'
                'import structlog, ddtrace\n'
                'log = structlog.get_logger()\n'
                'span = ddtrace.tracer.current_span()\n'
                'log.info("event_name", dd_trace_id=span.trace_id if span else None, key=value)'
            )
        return (
            '# Use structlog with OTEL trace injection:\n'
            'import structlog\n'
            'from opentelemetry import trace\n'
            'log = structlog.get_logger()\n'
            'ctx = trace.get_current_span().get_span_context()\n'
            'log.info("event_name", trace_id=format(ctx.trace_id, "032x"), key=value)'
        )

    if lang in ("javascript", "typescript"):
        if use_dd:
            return (
                "// Use pino with Datadog trace injection:\n"
                "const tracer = require('dd-trace').init();\n"
                "const logger = require('pino')();\n"
                "const span = tracer.scope().active();\n"
                "logger.info({ dd: { trace_id: span?.context().toTraceId(), span_id: span?.context().toSpanId() }, key: value }, 'event_name');"
            )
        return (
            "// Use pino with OTEL trace correlation:\n"
            "import { trace } from '@opentelemetry/api';\n"
            "const span = trace.getActiveSpan();\n"
            "const { traceId, spanId } = span?.spanContext() ?? {};\n"
            "logger.info({ traceId, spanId, key: value }, 'event_name');"
        )

    # Fallback
    if use_dd:
        return "Use pino/structlog with dd-trace trace injection (dd.trace_id, dd.span_id fields)."
    return "Use structured logging (key=value pairs) and inject OTEL trace/span IDs."


def span_start_snippet(lang: str, operation: str, instrumentation: str | None) -> str:
    """Return a minimal span-creation snippet for the given vendor."""
    instr = (instrumentation or "otel").strip().lower()
    use_dd = instr == "datadog"

    if lang == "go":
        if use_dd:
            return (
                f'span, ctx := tracer.StartSpanFromContext(ctx, "{operation}")\n'
                'defer span.Finish()\n'
                '// import "gopkg.in/DataDog/dd-trace-go.v1/ddtrace/tracer"'
            )
        return (
            f'ctx, span := otel.Tracer("service").Start(ctx, "{operation}")\n'
            'defer span.End()\n'
            '// import "go.opentelemetry.io/otel"'
        )

    if lang == "python":
        if use_dd:
            return (
                f'with ddtrace.tracer.trace("{operation}") as span:\n'
                '    ...\n'
                '# import ddtrace'
            )
        return (
            f'with tracer.start_as_current_span("{operation}") as span:\n'
            '    ...\n'
            '# from opentelemetry import trace; tracer = trace.get_tracer(__name__)'
        )

    if lang in ("javascript", "typescript"):
        if use_dd:
            return (
                f"const span = tracer.startSpan('{operation}');\n"
                "tracer.scope().activate(span, () => { /* ... */ span.finish(); });\n"
                "// const tracer = require('dd-trace').init();"
            )
        return (
            f"tracer.startActiveSpan('{operation}', (span) => {{\n"
            "  try { /* ... */ } finally { span.end(); }\n"
            "});\n"
            "// import { trace } from '@opentelemetry/api';"
        )

    if lang == "java":
        if use_dd:
            return (
                f'@Trace(operationName = "{operation}")\n'
                'public void method() {{ /* ... */ }}\n'
                '// import datadog.trace.api.Trace;'
            )
        return (
            f'Span span = tracer.spanBuilder("{operation}").startSpan();\n'
            'try (Scope scope = span.makeCurrent()) {{ /* ... */ }}\n'
            'finally {{ span.end(); }}\n'
            '// import io.opentelemetry.api.trace.*;'
        )

    if use_dd:
        return f"# dd-trace: create span for '{operation}'"
    return f"# otel: tracer.start_as_current_span('{operation}')"


_IAC_LANGUAGES = frozenset({
    "terraform", "hcl", "bicep", "pulumi", "cloudformation", "helm", "jsonnet",
})

_K8S_KEYWORDS = frozenset({"eks", "aks", "gke", "kubernetes", "k8s", "kube", "helm"})


def _is_iac(repo_type: str | None, iac_provider: str | None, language: str | None) -> bool:
    if (repo_type or "").strip().lower() == "iac":
        return True
    if iac_provider:
        return True
    if (language or "").strip().lower() in _IAC_LANGUAGES:
        return True
    return False


def _has_kubernetes(iac_provider: str | None, context_summary: str | None) -> bool:
    haystack = " ".join(filter(None, [iac_provider, context_summary])).lower()
    return any(kw in haystack for kw in _K8S_KEYWORDS)


def add_instrumentation_suggestion(
    instrumentation: str | None,
    obs_backend: str | None,
    language: str | None,
    repo_type: str | None = None,
    iac_provider: str | None = None,
    context_summary: str | None = None,
) -> str:
    """
    Return the appropriate 'add instrumentation/monitoring' suggestion when a repository
    has NO instrumentation at all. Respects repo_type/iac_provider so IaC repos receive
    infrastructure-level recommendations (Prometheus + kube-state-metrics, Datadog Operator)
    instead of application SDK guidance.
    """
    backend = (obs_backend or "").strip().lower()
    instr   = (instrumentation or "").strip().lower()

    # IaC / infrastructure repos need monitoring infrastructure, not application SDKs
    if _is_iac(repo_type, iac_provider, language):
        has_k8s = _has_kubernetes(iac_provider, context_summary)

        if backend == "datadog" or instr == "datadog":
            if has_k8s:
                return (
                    "This is an infrastructure repository provisioning Kubernetes resources. "
                    "Deploy the Datadog Agent using the Datadog Operator:\n"
                    "1. helm repo add datadog https://helm.datadoghq.com && helm install datadog-operator datadog/datadog-operator\n"
                    "2. kubectl create secret generic datadog-secret --from-literal api-key=<DD_API_KEY>\n"
                    "3. Apply a DatadogAgent CRD (datadoghq.com/v2alpha1) with clusterName and credentials.\n"
                    "This provides host metrics, container metrics, APM, log collection, and Kubernetes state metrics "
                    "without any application-level SDK changes. "
                    "See: https://docs.datadoghq.com/containers/kubernetes/installation/?tab=datadogoperator"
                )
            return (
                "This is an infrastructure repository. Deploy the Datadog Agent to collect infrastructure metrics. "
                "For containerized environments use the Datadog Operator (Kubernetes) or the Datadog Agent DaemonSet. "
                "No application SDK changes are needed — the Agent auto-discovers services via Autodiscovery."
            )

        # Prometheus / other / default for IaC
        if has_k8s:
            return (
                "This infrastructure repository provisions Kubernetes resources. "
                "Deploy the kube-prometheus stack to add cluster-wide monitoring:\n"
                "  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts\n"
                "  helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \\\n"
                "    --namespace monitoring --create-namespace\n"
                "This bundles Prometheus Operator, kube-state-metrics (Deployment/Pod/Node health), "
                "node-exporter (host CPU/memory/disk), and Grafana dashboards. "
                "Customize scrape targets via ServiceMonitor and PodMonitor CRDs. "
                "See: https://github.com/prometheus-operator/kube-prometheus"
            )
        return (
            "This is an infrastructure repository. Add a Prometheus scrape target and kube-state-metrics "
            "to expose infrastructure-level metrics. No application SDK is required — Prometheus collects "
            "metrics from exporters (node-exporter, kube-state-metrics, blackbox-exporter) deployed alongside "
            "your infrastructure. Define scrape configs in prometheus.yml or via ServiceMonitor CRDs if using "
            "the Prometheus Operator. See: https://prometheus.io/docs/prometheus/latest/installation/"
        )

    # User explicitly wants Datadog (either via obs_backend or instrumentation preference)
    if backend == "datadog" or instr == "datadog":
        lang_steps = {
            "python":     "pip install ddtrace",
            "go":         "go get gopkg.in/DataDog/dd-trace-go.v1/ddtrace/tracer",
            "javascript": "npm install dd-trace",
            "typescript": "npm install dd-trace",
            "java":       "Add dd-java-agent.jar to the JVM start command",
        }
        lang_step = lang_steps.get((language or "").lower(), "Install the Datadog APM tracer for your language")
        return (
            f"Add the Datadog APM tracer as the first step: {lang_step}. "
            "Set DD_SERVICE, DD_ENV, DD_VERSION environment variables. "
            "Auto-instrumentation covers HTTP, databases, and queues out of the box. "
            "Add manual spans with ddtrace.tracer.trace() for business-logic operations. "
            "Send traces to the Datadog Agent (DD_TRACE_AGENT_URL or DD_AGENT_HOST)."
        )

    # Grafana / Prometheus stack → OTEL or Prometheus client
    if backend in ("prometheus", "grafana"):
        lang_steps = {
            "python":     "pip install opentelemetry-sdk opentelemetry-exporter-prometheus",
            "go":         "go get go.opentelemetry.io/otel github.com/prometheus/client_golang",
            "javascript": "npm install @opentelemetry/sdk-node @opentelemetry/exporter-prometheus",
            "typescript": "npm install @opentelemetry/sdk-node @opentelemetry/exporter-prometheus",
            "java":       "Add opentelemetry-sdk and opentelemetry-exporter-prometheus to pom.xml",
        }
        lang_step = lang_steps.get((language or "").lower(), "Install OpenTelemetry SDK for your language")
        return (
            f"Add the OpenTelemetry SDK: {lang_step}. "
            "Configure a Prometheus exporter to expose /metrics. "
            "Create a MeterProvider with resource attributes (service.name, environment). "
            "Add traces with TracerProvider and export via OTLP to your Grafana/Tempo stack."
        )

    # Default — recommend OTEL (vendor-neutral)
    lang_steps = {
        "python":     "pip install opentelemetry-sdk opentelemetry-exporter-otlp",
        "go":         "go get go.opentelemetry.io/otel go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc",
        "javascript": "npm install @opentelemetry/sdk-node @opentelemetry/exporter-trace-otlp-http",
        "typescript": "npm install @opentelemetry/sdk-node @opentelemetry/exporter-trace-otlp-http",
        "java":       "Add opentelemetry-sdk and opentelemetry-exporter-otlp to pom.xml/build.gradle",
    }
    lang_step = lang_steps.get((language or "").lower(), "Install OpenTelemetry SDK for your language")
    return (
        f"Add the OpenTelemetry SDK: {lang_step}. "
        "Configure a TracerProvider with a resource (service.name, environment, version). "
        "Set up an OTLP exporter pointing to your observability backend (Datadog, Grafana, Jaeger, etc.). "
        "Auto-instrument your framework (FastAPI, Express, Spring, etc.) and add manual spans "
        "on critical business-logic operations."
    )
