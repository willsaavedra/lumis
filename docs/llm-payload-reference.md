# LLM Payload Reference — Análise de Cobertura

Este documento descreve o payload exato que é montado e enviado ao LLM durante uma análise de observabilidade.
Código-fonte: [`apps/agent/nodes/analyze_coverage.py`](../apps/agent/nodes/analyze_coverage.py) — função `_llm_analyze_coverage`.

---

## Visão geral do fluxo

```
AnalysisJob (DB)
    │ llm_provider = "anthropic" | "cerebra_ai"
    ▼
apps/agent/graph.py
    │ state["request"]["llm_provider"]
    ▼
analyze_coverage_node  (batches de 3-5 arquivos por chamada)
    │ monta system + user
    ▼
apps/agent/llm/chat_completion.py → chat_complete()
    │
    ├─► Anthropic API (claude-sonnet / claude-haiku)
    └─► CerebraAI vLLM  POST /v1/chat/completions (Qwen/Qwen3.5-35B-A3B-FP8)
```

Os arquivos do repositório são divididos em **batches de 3–5 arquivos** (≤ 3 000 chars de conteúdo por arquivo). Cada batch gera **uma chamada independente** ao LLM com o mesmo `system` e um `user` diferente.

---

## Parâmetros HTTP (CerebraAI / vLLM)

```http
POST http://52.86.35.131:8001/v1/chat/completions
Content-Type: application/json

{
  "model":       "Qwen/Qwen3.5-35B-A3B-FP8",
  "stream":      false,
  "temperature": 0.4,
  "top_p":       0.9,
  "max_tokens":  2500,
  "messages": [
    { "role": "system", "content": "<ver seção SYSTEM abaixo>" },
    { "role": "user",   "content": "<ver seção USER abaixo>" }
  ]
}
```

Para **Claude (Anthropic)** o conteúdo é idêntico mas usa o SDK com `temperature=0.3`, `top_p=1.0`, `max_tokens=2500`.

---

## Prompt SYSTEM

O system prompt é **fixo por análise** — não muda entre batches. Composto de:

```
You are an expert SRE auditing code for observability gaps (prompt version: coverage-v2.0).

── RAG section (se houver chunks relevantes no knowledge_chunks) ──────────────
[Relevant knowledge base context]
...chunks de boas práticas e padrões do tenant...

── IaC constraint (se repo_type = "iac") ──────────────────────────────────────
## IaC REPOSITORY — NON-NEGOTIABLE CONSTRAINTS
This is an Infrastructure-as-Code repository (terraform).
NEVER suggest: Python imports, Node.js/npm packages, dd-trace, opentelemetry SDK,
or any application runtime library.
ALL fixes MUST be infrastructure-native: Terraform variables, data sources,
Helm values, Kubernetes manifests, or shell/CLI commands.

── Instrumentation constraint (baseado no campo instrumentation do repo) ──────
## INSTRUMENTATION CONSTRAINT
Instrumentation library in use: OpenTelemetry SDK (vendor-neutral)
→ ALL suggestions MUST use OpenTelemetry SDK APIs.
→ NEVER suggest Datadog dd-trace, New Relic, or other vendor-specific SDKs.

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

Do NOT report missing tests, missing error handling, or style issues.
```

---

## Prompt USER

O user prompt **varia por batch**. Inclui contexto do repo + conteúdo real dos arquivos.

```
Analyze these files for observability gaps:
Repository type: app (api)
Primary language(s): go
Instrumentation library: OpenTelemetry SDK (vendor-neutral)
  → Flag gaps where OTEL spans/metrics/logs are expected but missing.
  → Highlight incorrect or missing resource attributes.
Observability backend / destination: datadog
Datadog standard tags: env:production, service:checkout-service, team:payments
Service name in observability backend: checkout-service

Repository context (from README/docs):
This is the checkout microservice responsible for processing payment transactions
and coordinating with inventory and billing services. Written in Go, uses PostgreSQL
and communicates with downstream services via gRPC.

Already-instrumented Datadog metrics: checkout.requests, checkout.errors, checkout.latency

Call graph coverage map (annotated):
```json
{
  "handler_checkout": {
    "name": "HandleCheckout",
    "type": "handler",
    "status": "uninstrumented"
  },
  "db_insert_order": {
    "name": "InsertOrder",
    "type": "db_call",
    "status": "instrumented"
  },
  "grpc_billing": {
    "name": "CallBillingService",
    "type": "http_client",
    "status": "uninstrumented"
  }
}
```

Language-specific detection checklist:
[GO]
- Check if http.Handler / gin / echo / chi / fiber functions create a span with otel.Tracer().Start(ctx, "name")
- Verify goroutines propagate context (pass ctx, not context.Background())
- Check db/sql calls use otelsql or pass ctx to QueryContext/ExecContext
- gRPC calls should use otelgrpc interceptors
- Verify error paths call span.RecordError(err) + span.SetStatus(codes.Error, msg)
- Check log statements use structured logging (slog/zerolog) with trace_id/span_id fields

File: src/checkout/main.go | Language: go | Obs-imports: otel
```go
package main

import (
    "context"
    "net/http"
    "log"

    "github.com/company/checkout/db"
    "github.com/company/checkout/billing"
)

func HandleCheckout(w http.ResponseWriter, r *http.Request) {
    ctx := r.Context()

    order, err := db.InsertOrder(ctx, r.Body)
    if err != nil {
        log.Println("error inserting order", err)
        http.Error(w, "internal error", 500)
        return
    }

    if err := billing.Charge(ctx, order); err != nil {
        log.Println("billing failed", err)
        http.Error(w, "billing error", 500)
        return
    }

    w.WriteHeader(200)
}
```

File: src/checkout/billing.go | Language: go | Obs-imports: unknown
```go
package billing

import (
    "context"
    "google.golang.org/grpc"
)

func Charge(ctx context.Context, order Order) error {
    conn, _ := grpc.Dial("billing-service:50051")
    client := billingpb.NewBillingClient(conn)
    _, err := client.ProcessPayment(ctx, &billingpb.PaymentRequest{
        OrderId: order.ID,
        Amount:  order.Total,
    })
    return err
}
```

Return a JSON array of findings. Each finding MUST include ALL fields:
[{
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
  "suggestion": "Concrete fix using the correct language/paradigm for this file",
  "code_before": "Exact problematic code extracted from the file (2-8 lines)",
  "code_after": "Corrected version of the same code snippet — syntactically valid"
}]

CRITICAL for code_before / code_after:
- Extract the REAL lines from the file content shown above — do NOT invent placeholder code
- code_before must match what is actually in the file at line_start..line_end
- code_after must be syntactically correct for the file's language
- Keep both snippets concise (2-8 lines each)

Return ONLY the JSON array — no markdown fences, no explanations.
```

---

## Resposta esperada do LLM

```json
[
  {
    "pillar": "traces",
    "severity": "critical",
    "dimension": "coverage",
    "confidence": "high",
    "title": "HTTP handler HandleCheckout has no span",
    "description": "The entry-point handler for checkout does not create an OpenTelemetry span. Any error or latency in this critical payment path will be invisible in traces.",
    "file_path": "src/checkout/main.go",
    "line_start": 11,
    "line_end": 13,
    "estimated_monthly_cost_impact": 0.0,
    "suggestion": "Wrap the handler body with a span: ctx, span := otel.Tracer(\"checkout\").Start(r.Context(), \"HandleCheckout\"); defer span.End(). Pass ctx downstream.",
    "code_before": "func HandleCheckout(w http.ResponseWriter, r *http.Request) {\n    ctx := r.Context()",
    "code_after": "func HandleCheckout(w http.ResponseWriter, r *http.Request) {\n    ctx, span := otel.Tracer(\"checkout\").Start(r.Context(), \"HandleCheckout\")\n    defer span.End()"
  },
  {
    "pillar": "traces",
    "severity": "critical",
    "dimension": "coverage",
    "confidence": "high",
    "title": "Error path without span error recording in HandleCheckout",
    "description": "Billing error is caught and logged with log.Println but span.RecordError and span.SetStatus are never called. The trace will show success even when billing fails.",
    "file_path": "src/checkout/main.go",
    "line_start": 21,
    "line_end": 24,
    "estimated_monthly_cost_impact": 0.0,
    "suggestion": "Add span.RecordError(err) and span.SetStatus(codes.Error, err.Error()) before returning, and replace log.Println with structured logging.",
    "code_before": "if err := billing.Charge(ctx, order); err != nil {\n    log.Println(\"billing failed\", err)\n    http.Error(w, \"billing error\", 500)\n    return\n}",
    "code_after": "if err := billing.Charge(ctx, order); err != nil {\n    span.RecordError(err)\n    span.SetStatus(codes.Error, err.Error())\n    slog.ErrorContext(ctx, \"billing_failed\", \"error\", err)\n    http.Error(w, \"billing error\", 500)\n    return\n}"
  },
  {
    "pillar": "traces",
    "severity": "warning",
    "dimension": "coverage",
    "confidence": "high",
    "title": "gRPC call to billing-service has no otelgrpc interceptor",
    "description": "grpc.Dial creates a connection without OpenTelemetry interceptors. Trace context will not be propagated to the billing service, breaking distributed tracing.",
    "file_path": "src/checkout/billing.go",
    "line_start": 10,
    "line_end": 11,
    "estimated_monthly_cost_impact": 0.0,
    "suggestion": "Add otelgrpc.UnaryClientInterceptor() to grpc.Dial options.",
    "code_before": "conn, _ := grpc.Dial(\"billing-service:50051\")",
    "code_after": "conn, _ := grpc.Dial(\"billing-service:50051\",\n    grpc.WithUnaryInterceptor(otelgrpc.UnaryClientInterceptor()),\n)"
  }
]
```

---

## Campos que compõem o `user` — de onde cada um vem

| Campo no prompt | Fonte |
|---|---|
| `Repository type` | `repo.repo_type` + `app_subtype` / `iac_provider` (tabela `repositories`) |
| `Primary language(s)` | `repo.language` (JSONB) |
| `Instrumentation library` | `repo.instrumentation` |
| `Observability backend` | `repo.observability_backend` |
| `Datadog standard tags` | `repo.obs_metadata.tags` |
| `Repository context` | `repo.context_summary` (gerado pelo `context_discovery` node) |
| `Already-instrumented metrics` | Resultado do node `fetch_dd_coverage` (opcional) |
| `Call graph coverage map` | Resultado do node `build_call_graph` (AST) |
| `Language-specific hints` | Dicionário hardcoded `_LANG_DETECTION_HINTS` no próprio arquivo |
| `RAG context` | Chunks recuperados de `knowledge_chunks` pelo node `retrieve_context` |
| `File: ... \`\`\`lang ... \`\`\`` | Conteúdo real do arquivo clonado, truncado em 3 000 chars |

---

## Outros nós que também chamam o LLM

| Nó | Arquivo | Propósito | `max_tokens` |
|---|---|---|---|
| `pre_triage` | `nodes/pre_triage.py` | Classifica relevância de arquivos ambíguos (0/1/2) | 1 024 |
| `context_discovery` | `nodes/context_discovery.py` | Gera `context_summary` do repo (parágrafo livre) | 1 024 |
| `generate_suggestions` | `nodes/generate_suggestions.py` | Gera `code_before`/`code_after` detalhado para cada finding | 4 000 |
| `fix_pr_service` | `services/fix_pr_service.py` | Reescreve arquivo completo com correções OTel | 8 000 |
