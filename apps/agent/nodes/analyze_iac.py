"""Node: Analyze IaC files for observability gaps (Terraform, Helm, CDK)."""
from __future__ import annotations

import re
import structlog

from apps.agent.nodes.base import publish_progress, publish_thought
from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Terraform static rules
# Each rule is (regex_on_resource_block, title, description, severity, impact_usd)
# ---------------------------------------------------------------------------
_TERRAFORM_RULES: list[dict] = [
    {
        "resource_pattern": r'resource\s+"aws_sqs_queue"\s+"[^"]+"\s*\{',
        "missing_pattern": r'aws_cloudwatch_metric_alarm',
        "scope": "module",  # check if missing anywhere in the same module
        "pillar": "metrics",
        "severity": "critical",
        "title": "SQS queue without CloudWatch alarm",
        "description": (
            "An aws_sqs_queue resource is defined but no aws_cloudwatch_metric_alarm "
            "monitors queue depth or DLQ size. Silent queue backup will go undetected."
        ),
        "estimated_monthly_cost_impact": 0.0,
    },
    {
        "resource_pattern": r'resource\s+"aws_lambda_function"\s+"[^"]+"\s*\{',
        "missing_pattern": r'datadog|otel|opentelemetry|lambda_layer',
        "scope": "block",
        "pillar": "traces",
        "severity": "critical",
        "title": "Lambda function without observability layer",
        "description": (
            "aws_lambda_function does not reference a Datadog or OTel Lambda layer. "
            "Invocations, cold starts, and errors will not be visible in your APM backend."
        ),
        "estimated_monthly_cost_impact": 0.0,
    },
    {
        "resource_pattern": r'resource\s+"aws_db_instance"\s+"[^"]+"\s*\{',
        "missing_pattern": r'monitoring_interval\s*=\s*(?!0\b)',
        "scope": "block",
        "pillar": "metrics",
        "severity": "warning",
        "title": "RDS instance with Enhanced Monitoring disabled",
        "description": (
            "aws_db_instance has monitoring_interval = 0 (default). "
            "Enhanced Monitoring (monitoring_interval >= 15) provides OS-level metrics "
            "critical for query performance analysis."
        ),
        "estimated_monthly_cost_impact": 0.0,
        "inverted": True,  # finding fires when the GOOD pattern is ABSENT
    },
    {
        "resource_pattern": r'resource\s+"aws_ecs_service"\s+"[^"]+"\s*\{',
        "missing_pattern": r'enable_execute_command|datadog|otel',
        "scope": "block",
        "pillar": "traces",
        "severity": "warning",
        "title": "ECS service without observability agent sidecar",
        "description": (
            "aws_ecs_service does not reference a Datadog agent, OTel Collector, "
            "or enable_execute_command for live debugging. "
            "Distributed traces will be missing for this service."
        ),
        "estimated_monthly_cost_impact": 0.0,
    },
    {
        "resource_pattern": r'resource\s+"[^"]+"\s+"[^"]+"\s*\{',
        "missing_pattern": r'"env"\s*[:=]|"service"\s*[:=]|"team"\s*[:=]',
        "scope": "block",
        "pillar": "pipeline",
        "severity": "info",
        "title": "Resource missing standard observability tags (env/service/team)",
        "description": (
            "IaC resource does not declare standard tags: env, service, team. "
            "These are required for metric filtering and cost attribution in most APM platforms."
        ),
        "estimated_monthly_cost_impact": 0.0,
    },
]

# ---------------------------------------------------------------------------
# Helm template static rules
# ---------------------------------------------------------------------------
_HELM_RULES: list[dict] = [
    {
        "pattern": r'kind:\s*Deployment',
        "missing_pattern": r'ad\.datadoghq\.com/',
        "scope": "manifest",
        "pillar": "traces",
        "severity": "critical",
        "title": "Kubernetes Deployment without Datadog auto-discovery annotations",
        "description": (
            "Deployment manifest has no ad.datadoghq.com/ annotations. "
            "Datadog Agent will not auto-instrument this workload for APM, logs, or metrics."
        ),
        "estimated_monthly_cost_impact": 0.0,
    },
    {
        "pattern": r'livenessProbe\s*:',
        "missing_pattern": r'readinessProbe\s*:',
        "scope": "manifest",
        "pillar": "pipeline",
        "severity": "warning",
        "title": "livenessProbe defined without readinessProbe",
        "description": (
            "A livenessProbe is configured but no readinessProbe is present. "
            "Traffic will be sent to pods that are not yet ready, causing elevated error rates."
        ),
        "estimated_monthly_cost_impact": 0.0,
    },
    {
        "pattern": r'kind:\s*Deployment|kind:\s*StatefulSet',
        "missing_pattern": r'kind:\s*PodDisruptionBudget',
        "scope": "directory",
        "pillar": "pipeline",
        "severity": "info",
        "title": "No PodDisruptionBudget found in Helm chart",
        "description": (
            "No PodDisruptionBudget manifest is present in the Helm chart directory. "
            "Rolling updates and node maintenance may cause complete availability gaps."
        ),
        "estimated_monthly_cost_impact": 0.0,
    },
]


# ---------------------------------------------------------------------------
# File extension classifiers
# ---------------------------------------------------------------------------
_TERRAFORM_EXTS = (".tf", ".hcl")
_HELM_EXTS = (".yaml", ".yml")
_HELM_TEMPLATE_PATH = re.compile(r"templates/|charts/", re.IGNORECASE)


def _is_terraform(path: str) -> bool:
    return any(path.endswith(ext) for ext in _TERRAFORM_EXTS)


def _is_helm_template(path: str) -> bool:
    return any(path.endswith(ext) for ext in _HELM_EXTS) and bool(_HELM_TEMPLATE_PATH.search(path))


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def _analyze_terraform_file(content: str, path: str) -> list[dict]:
    findings: list[dict] = []
    for rule in _TERRAFORM_RULES:
        blocks = list(re.finditer(rule["resource_pattern"], content))
        if not blocks:
            continue

        for m in blocks:
            block_start = m.start()
            # Determine search scope
            if rule["scope"] == "block":
                # Find matching closing brace (naïve depth counter)
                depth = 0
                pos = block_start
                for ch in content[block_start:]:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    pos += 1
                search_text = content[block_start:pos + 1]
            else:
                # module / directory scope — use entire file content
                search_text = content

            has_good_pattern = bool(re.search(rule["missing_pattern"], search_text, re.IGNORECASE))
            inverted = rule.get("inverted", False)

            # Fire when good pattern is absent (normal) OR present (inverted)
            if (not inverted and not has_good_pattern) or (inverted and not has_good_pattern):
                line_no = content[:block_start].count("\n") + 1
                findings.append({
                    "pillar": rule["pillar"],
                    "severity": rule["severity"],
                    "dimension": "coverage",
                    "title": rule["title"],
                    "description": rule["description"],
                    "file_path": path,
                    "line_start": line_no,
                    "line_end": line_no + 5,
                    "suggestion": None,
                    "estimated_monthly_cost_impact": rule["estimated_monthly_cost_impact"],
                    "confidence": "high",
                })

    return findings


def _analyze_helm_files(files: list[dict]) -> list[dict]:
    """
    Analyze a collection of Helm template files for observability gaps.
    Some rules operate per-manifest, others look across all files (directory scope).
    """
    findings: list[dict] = []
    combined_content = "\n".join(f.get("content", "") for f in files)

    for rule in _HELM_RULES:
        if rule["scope"] == "directory":
            # Check across all files
            has_trigger = bool(re.search(rule["pattern"], combined_content, re.IGNORECASE))
            has_good = bool(re.search(rule["missing_pattern"], combined_content, re.IGNORECASE))
            if has_trigger and not has_good:
                findings.append({
                    "pillar": rule["pillar"],
                    "severity": rule["severity"],
                    "dimension": "coverage",
                    "title": rule["title"],
                    "description": rule["description"],
                    "file_path": "helm/templates/",
                    "line_start": 1,
                    "line_end": 1,
                    "suggestion": None,
                    "estimated_monthly_cost_impact": rule["estimated_monthly_cost_impact"],
                    "confidence": "medium",
                })
        else:
            # Per-manifest check
            for f in files:
                content = f.get("content", "")
                path = f.get("path", "")
                if not re.search(rule["pattern"], content, re.IGNORECASE):
                    continue
                has_good = bool(re.search(rule["missing_pattern"], content, re.IGNORECASE))
                if not has_good:
                    findings.append({
                        "pillar": rule["pillar"],
                        "severity": rule["severity"],
                        "dimension": "coverage",
                        "title": rule["title"],
                        "description": rule["description"],
                        "file_path": path,
                        "line_start": 1,
                        "line_end": 1,
                        "suggestion": None,
                        "estimated_monthly_cost_impact": rule["estimated_monthly_cost_impact"],
                        "confidence": "high",
                    })

    return findings


async def analyze_iac_node(state: AgentState) -> dict:
    """
    IaC assessment node.

    Runs in parallel with analyze_coverage when:
      - repo_type == "iac"
      - OR .tf / Helm template files are detected in the changeset

    Applies static rule sets for:
      - Terraform (.tf / .hcl): SQS, Lambda, RDS, ECS, resource tags
      - Helm templates: Datadog annotations, readinessProbe, PDB
    """
    await publish_progress(state, "analyzing", 52, "Analyzing IaC for observability gaps...", stage_index=5)

    changed_files = state.get("changed_files", [])
    findings: list[dict] = list(state.get("findings", []))

    tf_files = [f for f in changed_files if _is_terraform(f.get("path", "")) and f.get("content")]
    helm_files = [f for f in changed_files if _is_helm_template(f.get("path", "")) and f.get("content")]

    for f in tf_files:
        new_findings = _analyze_terraform_file(f["content"], f["path"])
        findings.extend(new_findings)
        log.info("iac_terraform_analyzed", file=f["path"], findings=len(new_findings))

    if helm_files:
        helm_findings = _analyze_helm_files(helm_files)
        findings.extend(helm_findings)
        log.info("iac_helm_analyzed", files=len(helm_files), findings=len(helm_findings))

    total = len(tf_files) + len(helm_files)
    await publish_thought(state, "analyze_iac", f"Scanned {total} IaC files — {len(findings)} findings", status="done")
    await publish_progress(state, "analyzing", 56, f"IaC analysis complete: {total} files scanned.", stage_index=5)
    return {"findings": findings}


def has_iac_files(state: AgentState) -> bool:
    """Return True if the changeset contains IaC files worth analyzing."""
    repo_context = state.get("repo_context") or {}
    if repo_context.get("repo_type") == "iac":
        return True
    changed_files = state.get("changed_files", [])
    return any(
        _is_terraform(f.get("path", "")) or _is_helm_template(f.get("path", ""))
        for f in changed_files
    )
