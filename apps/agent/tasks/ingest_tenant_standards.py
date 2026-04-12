"""
Celery task: ingest_tenant_standards

Event-driven: triggered when a lumis.yaml file is found in a repository during analysis,
or manually via POST /api/v1/rag/ingest/standards.

Parses lumis.yaml, converts each rule to a human-readable text chunk,
embeds and upserts into knowledge_chunks with the tenant's ID.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog
import yaml
from opentelemetry import trace

from apps.worker.celery_app import celery_app
from apps.agent.tasks.rag_shared import (
    embed_texts,
    upsert_chunks,
    delete_tenant_source_chunks,
)

log = structlog.get_logger(__name__)

# Tenant standards chunks expire in 90 days (refreshed on each lumis.yaml change)
_STANDARDS_EXPIRES_DAYS = 90


@celery_app.task(name="apps.agent.tasks.ingest_tenant_standards", bind=True, max_retries=2)
def ingest_tenant_standards(self, tenant_id: str, yaml_content: str, repo_full_name: str = "") -> dict:
    """
    Parse lumis.yaml and ingest each rule as a separate knowledge chunk.
    Invalidates all previous tenant_standards chunks for this tenant first.
    """
    log.info("ingest_tenant_standards_started", tenant_id=tenant_id, repo=repo_full_name)
    return asyncio.run(_run(tenant_id, yaml_content, repo_full_name))


async def _run(tenant_id: str, yaml_content: str, repo_full_name: str) -> dict:
    try:
        config = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        log.warning("lumis_yaml_parse_error", tenant_id=tenant_id, error=str(e))
        return {"status": "error", "detail": str(e)}

    if not isinstance(config, dict):
        return {"status": "error", "detail": "lumis.yaml must be a YAML mapping"}

    chunks_text = _extract_rule_chunks(config, repo_full_name)
    if not chunks_text:
        ctx = trace.get_current_span().get_span_context()
        log.info("no_rules_found_in_lumis_yaml", trace_id=format(ctx.trace_id, "032x"), tenant_id=tenant_id)
        return {"inserted": 0}

    embeddings = await embed_texts(chunks_text)

    chunks = [
        {
            "content": c,
            "embedding": e,
            "metadata": {
                "source": "lumis.yaml",
                "repo": repo_full_name,
                "tenant_id": tenant_id,
            },
        }
        for c, e in zip(chunks_text, embeddings)
    ]

    # Invalidate old standards for this tenant before re-ingesting
    deleted = await delete_tenant_source_chunks(tenant_id, "tenant_standards")

    inserted = await upsert_chunks(
        chunks,
        tenant_id=tenant_id,
        source_type="tenant_standards",
        expires_days=_STANDARDS_EXPIRES_DAYS,
    )

    log.info(
        "ingest_tenant_standards_complete",
        tenant_id=tenant_id,
        deleted=deleted,
        inserted=inserted,
    )
    return {"inserted": inserted, "deleted": deleted}


def _extract_rule_chunks(config: dict, repo: str) -> list[str]:
    """
    Convert lumis.yaml rules into human-readable text chunks.
    Each logical rule becomes a separate chunk (~100-200 tokens, atomic).

    Example lumis.yaml structure:
      version: "1.0"
      standards:
        metrics:
          naming_pattern: "^acme\\.{service}\\.{operation}\\.{unit}$"
          required_tags: [env, service, team]
          forbidden_labels: [user_id, request_id]
        logs:
          library: zap
          min_level_prod: info
          required_fields: [trace_id, span_id]
        traces:
          sdk_version: ">=1.24.0"
          sampler: tail_based
          ignored_routes: [/health, /ready]
        compliance:
          pii_fields: [email, cpf, phone]
    """
    chunks = []
    version = config.get("version", "1.0")
    standards = config.get("standards", {})
    prefix = f"Repository: {repo} | lumis.yaml v{version} |"

    # Metrics standards
    metrics = standards.get("metrics", {})
    if metrics:
        if naming := metrics.get("naming_pattern"):
            chunks.append(
                f"{prefix} METRICS NAMING CONVENTION: All metric names must match the pattern: {naming}. "
                f"Metrics that do not follow this naming convention are non-compliant."
            )
        if required_tags := metrics.get("required_tags"):
            tags_str = ", ".join(required_tags)
            chunks.append(
                f"{prefix} REQUIRED METRIC TAGS: Every metric must include these tags/labels: {tags_str}. "
                f"Missing any of these tags is a compliance violation."
            )
        if forbidden := metrics.get("forbidden_labels"):
            fb_str = ", ".join(forbidden)
            chunks.append(
                f"{prefix} FORBIDDEN METRIC LABELS: The following high-cardinality labels must NOT be used "
                f"as metric labels: {fb_str}. Using these causes metric explosion and high cost."
            )

    # Logs standards
    logs = standards.get("logs", {})
    if logs:
        if library := logs.get("library"):
            chunks.append(
                f"{prefix} LOG LIBRARY: The approved logging library is '{library}'. "
                f"Using other logging libraries (e.g. fmt.Printf, print(), console.log) is non-compliant."
            )
        if min_level := logs.get("min_level_prod"):
            chunks.append(
                f"{prefix} LOG LEVEL IN PRODUCTION: Minimum log level in production is '{min_level}'. "
                f"Debug logs in production code are a noise violation."
            )
        if required_fields := logs.get("required_fields"):
            fields_str = ", ".join(required_fields)
            chunks.append(
                f"{prefix} REQUIRED LOG FIELDS: Every structured log entry must include: {fields_str}. "
                f"Missing these fields makes logs unsearchable in the logging backend."
            )

    # Traces standards
    traces = standards.get("traces", {})
    if traces:
        if sdk_version := traces.get("sdk_version"):
            chunks.append(
                f"{prefix} OTEL SDK VERSION: The approved minimum OTel SDK version is {sdk_version}. "
                f"Using older versions may miss critical bug fixes."
            )
        if sampler := traces.get("sampler"):
            chunks.append(
                f"{prefix} TRACE SAMPLER: The approved sampling strategy is '{sampler}'. "
                f"Head-based sampling at 100% in production is a cost violation."
            )
        if ignored := traces.get("ignored_routes"):
            routes_str = ", ".join(ignored)
            chunks.append(
                f"{prefix} IGNORED ROUTES: These routes should NOT be traced (health/readiness checks): "
                f"{routes_str}. Adding spans to these routes creates noise."
            )

    # Compliance
    compliance = standards.get("compliance", {})
    if compliance:
        if pii := compliance.get("pii_fields"):
            pii_str = ", ".join(pii)
            chunks.append(
                f"{prefix} PII FIELDS: The following fields contain PII and must NEVER appear in logs, "
                f"traces, or metrics labels: {pii_str}. This is a critical compliance violation (LGPD/GDPR)."
            )
        if env_tags := compliance.get("environment_tags"):
            env_str = ", ".join(f"{k}={v}" for k, v in env_tags.items())
            chunks.append(
                f"{prefix} ENVIRONMENT TAG MAPPING: Use these tag values for environments: {env_str}. "
                f"Inconsistent environment tags break cross-service dashboards."
            )

    # Raw custom rules (any extra keys)
    custom = {k: v for k, v in config.items() if k not in ("version", "standards")}
    for key, value in custom.items():
        chunks.append(
            f"{prefix} CUSTOM RULE '{key}': {_flatten_value(value)}"
        )

    return chunks


def _flatten_value(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)
