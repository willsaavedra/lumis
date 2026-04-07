"""
Celery task: ingest_global_docs

Runs every Monday at 02:00 UTC. Downloads OTel semantic conventions + SDK docs
and Datadog integration guides, chunks them, embeds via OpenAI, and upserts
into knowledge_chunks with tenant_id=NULL (shared by all tenants).

Also ingests curated static knowledge from workshop materials and internal docs
(e.g. otel_auto_vs_manual_instrumentation.md, file_triage_guide.md).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from apps.worker.celery_app import celery_app
from apps.agent.tasks.rag_shared import (
    chunk_by_sections,
    embed_texts,
    upsert_chunks,
    delete_expired_chunks,
)
from apps.agent.tasks.static_observability_fe_mobile import (
    FE_MOBILE_DOC_URLS,
    STATIC_OBSERVABILITY_FE_MOBILE,
)

log = structlog.get_logger(__name__)

# OTel docs sources: (url, language_hint, pillar_hint)
_OTEL_SDK_DOCS: list[tuple[str, str, str]] = [
    ("https://opentelemetry.io/docs/languages/go/instrumentation/", "go", "traces"),
    ("https://opentelemetry.io/docs/languages/python/instrumentation/", "python", "traces"),
    ("https://opentelemetry.io/docs/languages/java/instrumentation/", "java", "traces"),
    ("https://opentelemetry.io/docs/languages/js/instrumentation/", "node", "traces"),
    ("https://opentelemetry.io/docs/concepts/signals/metrics/", None, "metrics"),
    ("https://opentelemetry.io/docs/concepts/signals/logs/", None, "logs"),
    ("https://opentelemetry.io/docs/concepts/context-propagation/", None, "traces"),
]

_DD_DOCS: list[tuple[str, str | None, str]] = [
    ("https://docs.datadoghq.com/tracing/trace_collection/automatic_instrumentation/", None, "traces"),
    ("https://docs.datadoghq.com/logs/log_collection/", None, "logs"),
    ("https://docs.datadoghq.com/metrics/", None, "metrics"),
    ("https://docs.datadoghq.com/tracing/guide/add_span_md_and_graph_its_requests/", None, "traces"),
    # Kubernetes / infra monitoring
    ("https://docs.datadoghq.com/containers/kubernetes/installation/?tab=datadogoperator", None, "metrics"),
    ("https://docs.datadoghq.com/containers/datadog_operator", None, "metrics"),
]

# Prometheus docs: (url, language_hint, pillar_hint)
_PROMETHEUS_DOCS: list[tuple[str, str | None, str]] = [
    ("https://prometheus.io/docs/prometheus/latest/installation/", None, "metrics"),
    ("https://prometheus.io/docs/practices/naming/", None, "metrics"),
    ("https://prometheus.io/docs/practices/instrumentation/", None, "metrics"),
    # kube-prometheus README (raw markdown)
    (
        "https://raw.githubusercontent.com/prometheus-operator/kube-prometheus/main/README.md",
        None, "metrics",
    ),
]

_OTEL_SEMCONV_URL = (
    "https://raw.githubusercontent.com/open-telemetry/semantic-conventions/"
    "main/docs/general/attributes.md"
)

# TTL: global docs expire in 30 days (refreshed weekly anyway)
_DOC_EXPIRES_DAYS = 30

# ---------------------------------------------------------------------------
# Static curated knowledge — extracted from workshop materials and best-practice
# guides. This content is embedded directly (no HTTP fetch required).
# Format: (source_id, pillar, content)
# ---------------------------------------------------------------------------


def _load_static_knowledge_md(name: str) -> str:
    path = Path(__file__).resolve().parent.parent / "knowledge" / name
    return path.read_text(encoding="utf-8")


_STATIC_KNOWLEDGE: list[tuple[str, str, str]] = [
    (
        "terraform-iac-best-practices",
        "iac",
        """# Terraform / IaC Observability and Best Practices

## Core Principle: IaC Files Are NOT Application Code

Infrastructure-as-Code repositories (Terraform, Bicep, Pulumi, CloudFormation, Helm) define
infrastructure configuration. They do NOT contain application runtime code. When reviewing IaC
files for issues:

- NEVER suggest adding Python, Node.js, Go, or any application SDK import to `.tf` or `.hcl` files
- NEVER suggest OpenTelemetry SDK (`from opentelemetry import trace`) inside Terraform code
- Suggestions must be infrastructure-native: Terraform variables, data sources, locals, modules

## Common Anti-Pattern: Hardcoded Resource IDs

### Problem
```hcl
# eks/node.tf — BAD: hardcoded VPC ID prevents environment isolation
resource "aws_eks_node_group" "workers" {
  subnet_ids = ["subnet-0abc123", "subnet-0def456"]
  vpc_id     = "vpc-09e03cce60405767d"
}
```

### Fix: Use variables and data sources
```hcl
# variables.tf
variable "vpc_id" {
  description = "VPC ID where EKS nodes will be deployed"
  type        = string
  validation {
    condition     = can(regex("^vpc-", var.vpc_id))
    error_message = "vpc_id must start with 'vpc-'."
  }
}

# eks/node.tf — GOOD: uses variable
resource "aws_eks_node_group" "workers" {
  subnet_ids = data.aws_subnets.private.ids
  vpc_id     = var.vpc_id
}

# data.tf — discover subnets dynamically
data "aws_subnets" "private" {
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
  tags = {
    Tier = "private"
  }
}
```

## Environment Isolation Patterns

### Bad: Same values across all environments
```hcl
resource "aws_eks_cluster" "main" {
  name = "my-cluster"   # Will clash if deployed to multiple environments
}
```

### Good: Use terraform.workspace or var.environment
```hcl
variable "environment" {
  description = "Deployment environment (dev/staging/prod)"
  type        = string
}

resource "aws_eks_cluster" "main" {
  name = "my-cluster-${var.environment}"

  tags = {
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
```

## Secrets Management

### Bad: Hardcoded credentials
```hcl
resource "aws_db_instance" "main" {
  password = "SuperSecretP@ss123"   # Exposed in state file!
}
```

### Good: Use AWS Secrets Manager or SSM Parameter Store
```hcl
data "aws_secretsmanager_secret_version" "db_password" {
  secret_id = "/myapp/${var.environment}/db-password"
}

resource "aws_db_instance" "main" {
  password = jsondecode(data.aws_secretsmanager_secret_version.db_password.secret_string)["password"]
}
```

## Required Provider Version Constraints

```hcl
# terraform.tf — always pin provider versions
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"   # allows 5.x but not 6.x
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.25"
    }
  }
  required_version = ">= 1.6.0"
}
```

## Remote State Backend

```hcl
# backend.tf — never use local state in production
terraform {
  backend "s3" {
    bucket         = "my-terraform-state"
    key            = "eks/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "terraform-state-lock"
  }
}
```

## Required Tags for Cloud Governance

```hcl
locals {
  common_tags = {
    Environment  = var.environment
    Project      = var.project_name
    Team         = var.team_name
    ManagedBy    = "terraform"
    CostCenter   = var.cost_center
  }
}

resource "aws_instance" "example" {
  tags = merge(local.common_tags, {
    Name = "my-instance-${var.environment}"
  })
}
```

## Monitoring Resources in Terraform

For EKS clusters, add kube-prometheus-stack via Helm:

```hcl
# monitoring.tf
resource "helm_release" "kube_prometheus" {
  name             = "kube-prometheus-stack"
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  namespace        = "monitoring"
  create_namespace = true

  set {
    name  = "prometheus.prometheusSpec.retention"
    value = "30d"
  }

  set {
    name  = "grafana.adminPassword"
    value = data.aws_secretsmanager_secret_version.grafana_password.secret_string
  }
}
```

For Datadog:
```hcl
# monitoring.tf
resource "helm_release" "datadog_operator" {
  name       = "datadog-operator"
  repository = "https://helm.datadoghq.com"
  chart      = "datadog-operator"
  namespace  = "datadog"
  create_namespace = true
}

resource "kubernetes_secret" "datadog_secret" {
  metadata {
    name      = "datadog-secret"
    namespace = "datadog"
  }
  data = {
    api-key = data.aws_secretsmanager_secret_version.dd_api_key.secret_string
  }
}
```
""",
    ),
    (
        "kubernetes-infra-monitoring-best-practices",
        "metrics",
        """# Kubernetes & Infrastructure Monitoring Best Practices

## IaC Repositories and Observability

Infrastructure-as-Code (IaC) repositories (Terraform, Helm, Bicep, Pulumi) define and provision
infrastructure. They do NOT require application-level SDK instrumentation (OpenTelemetry SDK,
dd-trace). Instead, observability is added at the infrastructure layer using dedicated agents and
exporters deployed alongside the provisioned resources.

## Kubernetes Monitoring — kube-prometheus Stack (Recommended)

The **kube-prometheus stack** is the standard solution for Kubernetes cluster monitoring. It bundles:
- **Prometheus Operator**: Manages Prometheus instances via CRDs (ServiceMonitor, PodMonitor)
- **kube-state-metrics**: Exposes Kubernetes object health (Deployments, Pods, Nodes, Services)
- **node-exporter**: Host-level metrics (CPU, memory, disk, network) per node
- **Grafana**: Pre-built dashboards for cluster and workload visibility
- **Alertmanager**: Alert routing and deduplication

### Installation (Helm — recommended for production):
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \\
  --namespace monitoring --create-namespace
```

### Installation (kubectl manifests):
```bash
kubectl apply --server-side -f manifests/setup
kubectl wait --for condition=Established --all CustomResourceDefinition --namespace=monitoring
kubectl apply -f manifests/
```

## Key Kubernetes Metrics to Monitor

- **Node metrics** (node-exporter): CPU utilization, memory pressure, disk I/O, network bandwidth
- **Cluster state** (kube-state-metrics): Pod restarts, Deployment replicas ready, Job completions
- **API Server**: Request rate, latency p99, etcd latency
- **Kubelet**: Container resource limits, garbage collection
- **Workload RED metrics**: Request rate, Error rate, Duration — via application ServiceMonitors

## Prometheus Operator Custom Resources

- **ServiceMonitor**: Scrapes metrics from Kubernetes Services by label selector
- **PodMonitor**: Scrapes metrics directly from Pods
- **PrometheusRule**: Defines recording rules and alert rules (managed by the Operator)
- **AlertmanagerConfig**: Configures routing and receivers for alert notifications

## When to Use Prometheus vs Datadog for Kubernetes

| Scenario | Recommendation |
|---|---|
| Open-source stack, Grafana dashboards | kube-prometheus (Prometheus Operator) |
| Existing Datadog contract | Datadog Agent via Datadog Operator |
| Multi-cloud, vendor-neutral | OpenTelemetry Collector → remote_write to any backend |
| EKS on AWS | kube-prometheus-stack or AWS Managed Prometheus (AMP) |
| AKS on Azure | kube-prometheus-stack or Azure Monitor for containers |
| GKE on GCP | kube-prometheus-stack or Google Managed Prometheus |

## Prometheus Best Practices for Infrastructure

### Metric Naming
- Use `_total` suffix for counters: `http_requests_total`
- Use `_seconds` for time: `job_duration_seconds`
- Use `_bytes` for sizes: `node_memory_usage_bytes`
- Prefix with application/subsystem: `kube_pod_status_ready`

### Labels
- Keep cardinality low — avoid user IDs, request IDs as label values
- Use labels to differentiate dimensions: `job`, `namespace`, `pod`, `container`
- Limit to < 10 label values per metric for production safety

### Alerting
- Alert on symptoms (high error rate, latency), not causes (CPU usage)
- Use `for:` duration to avoid flapping alerts (e.g., `for: 5m`)
- Set severity: critical (page), warning (ticket), info (dashboard)
""",
    ),
    (
        "datadog-kubernetes-operator-best-practices",
        "metrics",
        """# Datadog Agent on Kubernetes — Operator Installation

## Overview

For Kubernetes environments with Datadog as the observability backend, use the **Datadog Operator**
(recommended) instead of raw DaemonSet manifests. The Operator manages the Agent lifecycle,
validates configurations, and reports health via CRD status.

## Installation

### Step 1: Install the Datadog Operator via Helm
```bash
helm repo add datadog https://helm.datadoghq.com
helm install datadog-operator datadog/datadog-operator
kubectl create secret generic datadog-secret --from-literal api-key=<DATADOG_API_KEY>
```

### Step 2: Configure and deploy the DatadogAgent CRD
```yaml
apiVersion: datadoghq.com/v2alpha1
kind: DatadogAgent
metadata:
  name: datadog
spec:
  global:
    clusterName: <CLUSTER_NAME>
    site: datadoghq.com
    credentials:
      apiSecret:
        secretName: datadog-secret
        keyName: api-key
```

```bash
kubectl apply -f datadog-agent.yaml
```

## What the Datadog Agent Collects on Kubernetes

- **Infrastructure metrics**: CPU, memory, disk, network per node and container
- **Kubernetes state metrics**: Equivalent to kube-state-metrics (Pods, Deployments, Jobs)
- **APM traces**: Auto-discovered services via Autodiscovery annotations
- **Logs**: Container stdout/stderr collected and forwarded
- **Live Processes**: Real-time process list per node
- **Network Performance Monitoring**: Traffic between services (requires eBPF)

## Autodiscovery

The Datadog Agent uses Autodiscovery to configure integrations dynamically:
- Annotate Pods with `ad.datadoghq.com/<container>.check_names` to enable checks
- Use Cluster Check Runners for high-cardinality endpoint checks

## IaC Integration

When using Terraform to manage Kubernetes:
- Use the `helm_release` resource to deploy the Datadog Operator
- Use `kubernetes_secret` to manage the API key secret
- Store the API key in Vault or AWS Secrets Manager — never hardcode in Terraform state
""",
    ),
    (
        "otel-workshop-intro-observability",
        "traces",
        """# Introduction to Observability — Workshop Notes

## Telemetry vs Monitoring vs Observability

- **Telemetry**: Data generated by your application informing its runtime state.
- **Monitoring**: Using telemetry data to quickly answer frequent questions.
- **Observability**: The ability to use telemetry data to answer questions you don't yet have.

## The Three Pillars of Observability

### Logs
Logs are the record of important events for the application. Each event typically
contains a timestamp and a description.

**Best practices:**
- Use structured messages (JSON) with well-defined fields — not plain text.
- Write to stdout/stderr, not local disk. Use a central collector.
- Log lifecycle events: service startup (with versions, key configs), key state changes
  (DB connection lost/restored, new network topology).
- Log unexpected states: a critical error outside a request, unexpected dependency state.

**Anti-patterns (do NOT use logs for):**
- HTTP request transactions — use traces/spans instead.
- High-frequency expected events (e.g. cache invalidation) — use metrics/counters instead.
- Internal state (memory size, queue length, operation latency) — use metrics instead.

Decision rule: if an event can be analyzed in isolation → use a log.

### Metrics
Metrics are the numeric representation of an event, segmented by arbitrary dimensions.

**Types:**
- **Counters**: event counts, monotonic (e.g. video views) or up/down (current viewers).
- **Gauges** (fixed values): current temperature, memory usage, queue size.
- **Timers/Histograms**: duration between two events (e.g. service response time).

**Best practices:**
- Keep cardinality LOW — high-cardinality dimensions break metric databases.
- Measure KEY latencies, including calls to dependent services.
- Use counters instead of logging every occurrence of a specific event.

**The Four Golden Signals (Google SRE):**
1. **Traffic** — requests per second the app is receiving.
2. **Errors** — error rate returned by the app.
3. **Saturation** — percentage showing how much of the service is still free.
4. **Latency** — how long a given operation takes.

**RED Method (for services/applications):**
- **R**equests — number of requests. Include status as a dimension.
- **E**rrors — how many requests were errors. Store separately for easy percentage calc.
- **D**uration — how long the service took to respond.

**USE Method (for infrastructure):**
- **U**tilization — how much of the resource was used.
- **S**aturation — how much of the service is still free.
- **E**rrors — error rate.

Decision rule: if an event can be summarized as a number or analyzed in aggregate → use metrics.

### Traces (Distributed Tracing)
Traces record all steps taken during the execution of a business transaction,
potentially spanning multiple services across different stages.

**Key concepts:**
- **Context Propagation**: On every call (local or remote) the context is propagated.
  Context = trace ID + parent span ID + optional baggage.
- **Spans**: Events similar to logs, but with a duration and causality info (trace ID,
  parent span ID). Everything else is "extra" attributes.
- Traces don't really exist as a data structure — only individual spans that share the same trace ID.

**Best practices for spans:**
- Instrument the boundaries of your application: HTTP servers, DB calls, external service calls.
- Create spans for deviations from normal behavior.
- Instrument critical, problematic, or business-important algorithms.

**Anti-patterns:**
- Do NOT create spans for every method — less is more.
- Do NOT repeat the same operation multiple times within one span — create one span
  and store the execution count as an attribute.
- Do NOT create giant traces — use span links to break a business transaction into
  multiple connected traces when needed.

Decision rule: if an event belongs to a business transaction → it is a span in a trace.

## Instrumentation Requirements

**Application metrics and traces REQUIRE active instrumentation:**
- App instrumentation SDKs: OpenTelemetry SDK, Datadog APM (ddtrace), OpenTracing,
  OpenMetrics/Prometheus client.
- Infra/agent: Datadog Agent, OpenTelemetry Collector (otelcol).

A service that has NO instrumentation library and NO agent configured CANNOT emit
traces or metrics. Claiming a 100% metrics or traces score for an uninstrumented
service is invalid.

**Microservices context:**
In a microservices architecture, context propagation across service boundaries is
critical. Without proper W3C traceparent/tracestate header propagation, distributed
traces will be broken — each service will create isolated traces instead of a
connected view of the transaction.
""",
    ),
    (
        "otel-workshop-signals-best-practices",
        "metrics",
        """# Observability Signals — Best Practices Reference

## When to Use Each Signal

| Scenario | Signal to Use |
|---|---|
| Event that can be analyzed in isolation | Log |
| Event that can be summarized as a number | Metric |
| Event that belongs to a business transaction | Trace (span) |
| State of memory/CPU at a specific moment | Profile |
| Error stacktrace from a service | Error event |

## Structured Logging Best Practices
- Always emit structured JSON logs with: timestamp, level, service, trace_id, span_id.
- Include trace context (trace_id, span_id) so logs can be correlated with traces.
- Log at service boundaries: request received, response sent, errors, state changes.
- Avoid logging inside tight loops — use metrics counters instead.
- Use appropriate log levels: ERROR for unexpected states, WARN for degraded states,
  INFO for lifecycle events, DEBUG for development-only details.

## Metrics Best Practices
- Prefer histograms over averages for latency — p50/p95/p99 are more actionable.
- Always include http.status_code as a metric dimension for HTTP services.
- Do not use user IDs, session IDs, or other high-cardinality values as metric labels.
- Implement the RED method for every service: request_total, error_total, duration_seconds.
- Implement the USE method for every infrastructure resource.
- Set up SLO-based alerting: alert on error_rate > budget_burn_rate.

## Distributed Tracing Best Practices
- Propagate W3C trace context (traceparent, tracestate headers) on ALL cross-service calls.
- Every HTTP handler, gRPC handler, and message queue consumer should create a root span.
- Every outbound DB call, HTTP call, and cache operation should be wrapped in a child span.
- Set span status to ERROR on any exception or non-2xx HTTP response.
- Record exceptions on spans: span.record_exception(err) + span.set_status(ERROR).
- Add business context to spans as attributes: user_id, order_id, product_sku.
- Use semantic conventions for attribute names (http.method, db.system, messaging.system).

## Common Instrumentation Anti-Patterns
- **Broken traces**: Goroutines/async tasks launched WITHOUT propagating trace context.
- **Silent errors**: Exception caught and swallowed WITHOUT recording on span or logging.
- **Missing boundaries**: HTTP handler or queue consumer with NO entry span.
- **Log spam**: Logging every cache hit/miss instead of using a metric counter.
- **High-cardinality labels**: Using user IDs or request IDs as metric label values.
- **Trace noise**: Creating spans for every function call — only instrument meaningful boundaries.
""",
    ),
    (
        "otel-auto-vs-manual-instrumentation",
        "traces",
        _load_static_knowledge_md("otel_auto_vs_manual_instrumentation.md"),
    ),
    (
        "file-triage-guide",
        "coverage",
        _load_static_knowledge_md("file_triage_guide.md"),
    ),
]


@celery_app.task(name="apps.agent.tasks.ingest_global_docs", bind=True, max_retries=1)
def ingest_global_docs(self) -> dict:
    """Weekly ingestion of OTel and Datadog documentation into the global knowledge index."""
    log.info("ingest_global_docs_started")
    return asyncio.run(_run())


async def _run() -> dict:
    total_inserted = 0
    errors = []

    # 1. Static curated knowledge (workshop PDFs, internal best-practice guides)
    for source_id, pillar, content in _STATIC_KNOWLEDGE + STATIC_OBSERVABILITY_FE_MOBILE:
        try:
            inserted = await _ingest_static(source_id, pillar=pillar, content=content)
            total_inserted += inserted
            log.info("static_knowledge_ingested", source_id=source_id, inserted=inserted)
        except Exception as e:
            log.warning("static_knowledge_ingest_failed", source_id=source_id, error=str(e))
            errors.append(str(e))

    # 2. OTel Semantic Conventions YAML/Markdown
    try:
        inserted = await _ingest_url(
            _OTEL_SEMCONV_URL, source_type="otel_docs", language=None, pillar="traces",
            chunk_size=400,
        )
        total_inserted += inserted
        log.info("otel_semconv_ingested", inserted=inserted)
    except Exception as e:
        log.warning("otel_semconv_ingest_failed", error=str(e))
        errors.append(str(e))

    # 3. OTel SDK docs per language
    for url, lang, pillar in _OTEL_SDK_DOCS:
        try:
            inserted = await _ingest_url(
                url, source_type="otel_docs", language=lang, pillar=pillar,
            )
            total_inserted += inserted
        except Exception as e:
            log.warning("otel_doc_ingest_failed", url=url, error=str(e))
            errors.append(str(e))

    # 4. Datadog docs
    for url, lang, pillar in _DD_DOCS:
        try:
            inserted = await _ingest_url(
                url, source_type="dd_docs", language=lang, pillar=pillar,
            )
            total_inserted += inserted
        except Exception as e:
            log.warning("dd_doc_ingest_failed", url=url, error=str(e))
            errors.append(str(e))

    # 5. Prometheus docs (infra / Kubernetes monitoring)
    for url, lang, pillar in _PROMETHEUS_DOCS:
        try:
            inserted = await _ingest_url(
                url, source_type="otel_docs", language=lang, pillar=pillar,
            )
            total_inserted += inserted
            log.info("prometheus_doc_ingested", url=url, inserted=inserted)
        except Exception as e:
            log.warning("prometheus_doc_ingest_failed", url=url, error=str(e))
            errors.append(str(e))

    # 5b. Browser / mobile / Web Vitals docs
    for url, lang, pillar in FE_MOBILE_DOC_URLS:
        try:
            inserted = await _ingest_url(
                url, source_type="otel_docs", language=lang, pillar=pillar,
            )
            total_inserted += inserted
            log.info("fe_mobile_doc_ingested", url=url, inserted=inserted)
        except Exception as e:
            log.warning("fe_mobile_doc_ingest_failed", url=url, error=str(e))
            errors.append(str(e))

    # 6. TTL cleanup
    deleted = await delete_expired_chunks()

    log.info(
        "ingest_global_docs_complete",
        total_inserted=total_inserted,
        deleted_expired=deleted,
        errors=len(errors),
    )
    return {"inserted": total_inserted, "deleted": deleted, "errors": errors}


async def _ingest_static(
    source_id: str,
    *,
    pillar: str,
    content: str,
    chunk_size: int = 400,
) -> int:
    """Embed and upsert static/curated content into the global knowledge index."""
    chunks_text = chunk_by_sections(content, max_tokens=chunk_size, overlap_tokens=50)
    if not chunks_text:
        return 0

    embeddings = await embed_texts(chunks_text)

    chunks = [
        {
            "content": c,
            "embedding": e,
            "metadata": {"source_id": source_id, "pillar": pillar, "static": True},
        }
        for c, e in zip(chunks_text, embeddings)
    ]

    return await upsert_chunks(
        chunks,
        tenant_id=None,
        source_type="static_knowledge",
        language=None,
        pillar=pillar,
        expires_days=_DOC_EXPIRES_DAYS * 4,  # static content expires less often (120 days)
    )


async def _ingest_url(
    url: str,
    *,
    source_type: str,
    language: str | None,
    pillar: str | None,
    chunk_size: int = 400,
) -> int:
    """Fetch URL, chunk content, embed, and upsert."""
    import httpx

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "Lumis-RAG/1.0"})
        if resp.status_code != 200:
            log.warning("doc_fetch_failed", url=url, status=resp.status_code)
            return 0

        raw_text = resp.text

    # Strip HTML if needed
    text = _extract_text(raw_text)
    if not text.strip():
        return 0

    chunks_text = chunk_by_sections(text, max_tokens=chunk_size, overlap_tokens=50)
    if not chunks_text:
        return 0

    embeddings = await embed_texts(chunks_text)

    chunks = [
        {
            "content": c,
            "embedding": e,
            "metadata": {"source_url": url, "language": language, "pillar": pillar},
        }
        for c, e in zip(chunks_text, embeddings)
    ]

    return await upsert_chunks(
        chunks,
        tenant_id=None,
        source_type=source_type,
        language=language,
        pillar=pillar,
        expires_days=_DOC_EXPIRES_DAYS,
    )


def _extract_text(raw: str) -> str:
    """Strip HTML tags for basic text extraction."""
    import re

    # If it's markdown/plain text, return as-is
    if not raw.strip().startswith("<"):
        return raw

    # Basic HTML → text: remove scripts/styles, then strip tags
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    text = re.sub(r'\s{3,}', '\n\n', text)
    return text.strip()
