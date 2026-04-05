"""
OpenTelemetry instrumentation snippet generator.
Produces vendor-neutral OTel code in Go, Python, Java, and Node.js.
"""
from __future__ import annotations


class OTelSnippetGenerator:
    """Generate OTel instrumentation snippets for common patterns."""

    def get_span_snippet(self, language: str, function_name: str, span_name: str) -> str:
        """Generate a span creation snippet for the given language."""
        generators = {
            "go": self._go_span,
            "python": self._python_span,
            "java": self._java_span,
            "typescript": self._ts_span,
            "javascript": self._ts_span,
        }
        gen = generators.get(language)
        if not gen:
            return f"// Add OTel span for: {span_name}"
        return gen(function_name, span_name)

    def get_structured_log_snippet(self, language: str, event_name: str) -> str:
        """Generate a structured logging snippet."""
        snippets = {
            "go": f'slog.Info("{event_name}", "key1", value1, "key2", value2)',
            "python": f'logger.info("{event_name}", extra={{"key1": value1, "key2": value2}})',
            "java": f'log.info("{event_name}", kv("key1", value1), kv("key2", value2));',
            "typescript": f'logger.info({{ key1: value1, key2: value2 }}, "{event_name}")',
            "javascript": f'logger.info({{ key1: value1, key2: value2 }}, "{event_name}")',
        }
        return snippets.get(language, f'// Structured log: {event_name}')

    def get_metric_snippet(self, language: str, metric_name: str, metric_type: str = "counter") -> str:
        """Generate a metric recording snippet."""
        snippets = {
            "go": self._go_metric(metric_name, metric_type),
            "python": self._python_metric(metric_name, metric_type),
            "typescript": self._ts_metric(metric_name, metric_type),
        }
        return snippets.get(language, f"// Record metric: {metric_name}")

    def get_context_propagation_snippet(self, language: str) -> str:
        """Generate context propagation snippet for async/goroutine scenarios."""
        snippets = {
            "go": """// Propagate trace context to goroutine
ctx, span := tracer.Start(ctx, "background-task")
defer span.End()
go func(ctx context.Context) {
    // ctx carries the trace context
    doWork(ctx)
}(ctx)""",
            "python": """# Propagate trace context to async task
with tracer.start_as_current_span("async-task") as span:
    ctx = context.get_current()
    # Pass ctx to the async function
    await do_work(ctx)""",
            "typescript": """// Propagate trace context to async function
const span = tracer.startSpan('async-task');
const ctx = trace.setSpan(context.active(), span);
await context.with(ctx, async () => {
    await doWork();
    span.end();
});""",
        }
        return snippets.get(language, "// Add context propagation")

    def _go_span(self, function_name: str, span_name: str) -> str:
        return f"""import "go.opentelemetry.io/otel"

func {function_name}(ctx context.Context, ...) error {{
    ctx, span := otel.Tracer("service-name").Start(ctx, "{span_name}")
    defer span.End()

    // Add semantic attributes
    span.SetAttributes(
        attribute.String("service.name", "your-service"),
        // attribute.String("user.id", userID),  // AVOID: high cardinality
    )

    // ... function body ...

    if err != nil {{
        span.RecordError(err)
        span.SetStatus(codes.Error, err.Error())
        return err
    }}
    return nil
}}"""

    def _python_span(self, function_name: str, span_name: str) -> str:
        return f"""from opentelemetry import trace
from opentelemetry.trace import StatusCode

tracer = trace.get_tracer(__name__)

async def {function_name}(...):
    with tracer.start_as_current_span("{span_name}") as span:
        span.set_attribute("service.name", "your-service")
        try:
            # ... function body ...
            pass
        except Exception as e:
            span.record_exception(e)
            span.set_status(StatusCode.ERROR, str(e))
            raise"""

    def _java_span(self, function_name: str, span_name: str) -> str:
        return f"""import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.*;
import io.opentelemetry.context.Context;

private static final Tracer tracer = GlobalOpenTelemetry.getTracer("service-name");

public Result {function_name}(...) {{
    Span span = tracer.spanBuilder("{span_name}").startSpan();
    try (Scope scope = span.makeCurrent()) {{
        span.setAttribute("service.name", "your-service");
        // ... method body ...
        return result;
    }} catch (Exception e) {{
        span.recordException(e);
        span.setStatus(StatusCode.ERROR, e.getMessage());
        throw e;
    }} finally {{
        span.end();
    }}
}}"""

    def _ts_span(self, function_name: str, span_name: str) -> str:
        return f"""import {{ trace, context, SpanStatusCode }} from '@opentelemetry/api';

const tracer = trace.getTracer('service-name');

async function {function_name}(...): Promise<Result> {{
  const span = tracer.startSpan('{span_name}');
  return context.with(trace.setSpan(context.active(), span), async () => {{
    try {{
      span.setAttribute('service.name', 'your-service');
      // ... function body ...
      return result;
    }} catch (error) {{
      span.recordException(error as Error);
      span.setStatus({{ code: SpanStatusCode.ERROR }});
      throw error;
    }} finally {{
      span.end();
    }}
  }});
}}"""

    def _go_metric(self, metric_name: str, metric_type: str) -> str:
        if metric_type == "counter":
            return f"""import "go.opentelemetry.io/otel/metric"

var {metric_name}Counter metric.Int64Counter

func init() {{
    meter := otel.Meter("service-name")
    {metric_name}Counter, _ = meter.Int64Counter(
        "{metric_name}",
        metric.WithDescription("Description of the metric"),
    )
}}

// Usage (use stable labels, NOT user_id/trace_id):
{metric_name}Counter.Add(ctx, 1, metric.WithAttributes(
    attribute.String("status", "success"),
    attribute.String("env", "production"),
))"""
        return f"// {metric_type} metric: {metric_name}"

    def _python_metric(self, metric_name: str, metric_type: str) -> str:
        return f"""from opentelemetry import metrics

meter = metrics.get_meter(__name__)
{metric_name}_counter = meter.create_counter(
    "{metric_name}",
    description="Description of the metric",
)

# Usage (use stable labels, NOT user_id/trace_id):
{metric_name}_counter.add(1, {{"status": "success", "env": "production"}})"""

    def _ts_metric(self, metric_name: str, metric_type: str) -> str:
        return f"""import {{ metrics }} from '@opentelemetry/api';

const meter = metrics.getMeter('service-name');
const {metric_name}Counter = meter.createCounter('{metric_name}', {{
  description: 'Description of the metric',
}});

// Usage (use stable labels, NOT userId/traceId):
{metric_name}Counter.add(1, {{ status: 'success', env: 'production' }});"""
