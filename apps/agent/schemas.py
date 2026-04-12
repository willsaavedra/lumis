"""Pydantic schemas for agent state and data types."""
from __future__ import annotations

from typing import TypedDict, Any
from dataclasses import dataclass, field
from enum import Enum


class AnalysisType(str, Enum):
    QUICK = "quick"
    FULL = "full"
    REPOSITORY = "repository"

class ScopeType(str, Enum):
    FULL_REPO = "full_repo"
    SELECTION = "selection"
    CONTEXT = "context"


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Pillar(str, Enum):
    METRICS = "metrics"
    LOGS = "logs"
    TRACES = "traces"
    IAC = "iac"
    PIPELINE = "pipeline"


class Dimension(str, Enum):
    COST = "cost"
    SNR = "snr"
    PIPELINE = "pipeline"
    COMPLIANCE = "compliance"
    COVERAGE = "coverage"


@dataclass
class ChangedFile:
    path: str
    language: str | None = None
    relevance_score: int = 0  # 0=irrelevant, 1=low, 2=high (set by pre_triage)
    content: str | None = None
    domain: str | None = None
    file_role: str | None = None


@dataclass
class CallNode:
    name: str
    file_path: str
    line: int
    node_type: str  # "handler", "db_call", "http_client", "cache", "queue", "utility"
    callers: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)


@dataclass
class CallGraph:
    nodes: dict[str, CallNode] = field(default_factory=dict)
    entry_points: list[str] = field(default_factory=list)  # HTTP handlers, queue consumers
    io_nodes: list[str] = field(default_factory=list)  # DB, HTTP client, cache
    error_paths: list[str] = field(default_factory=list)  # try/catch, error returns


@dataclass
class CoverageMap:
    """Annotated call graph with observability coverage per node."""
    span_coverage: dict[str, str] = field(default_factory=dict)   # node -> present/missing/partial/noise
    log_coverage: dict[str, str] = field(default_factory=dict)    # node -> structured/unstructured/missing
    metric_coverage: dict[str, str] = field(default_factory=dict) # node -> present/missing/high_cardinality


@dataclass
class DatadogCoverage:
    """Existing Datadog instrumentation for a service."""
    metrics: list[str] = field(default_factory=list)
    monitors: list[dict] = field(default_factory=list)
    apm_services: list[str] = field(default_factory=list)
    dashboards: list[str] = field(default_factory=list)


@dataclass
class Finding:
    pillar: str
    severity: str
    dimension: str
    title: str
    description: str
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    suggestion: str | None = None
    estimated_monthly_cost_impact: float = 0.0


@dataclass
class EfficiencyScores:
    cost: int = 100
    snr: int = 100
    pipeline: int = 100
    compliance: int = 100
    metrics: int = 100
    logs: int = 100
    traces: int = 100
    global_score: int = 100


@dataclass
class NodeTokens:
    node: str = ""
    input: int = 0
    output: int = 0
    cached: int = 0
    cost_usd: float = 0.0
    cumulative_usd: float = 0.0


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    llm_calls: int = 0
    cost_usd: float = 0.0
    by_node: dict = field(default_factory=dict)


@dataclass
class AnalysisRequest:
    job_id: str
    tenant_id: str
    repo_id: str
    repo_full_name: str
    clone_url: str
    ref: str
    pr_number: int | None
    commit_sha: str | None
    changed_files: list[str]
    analysis_type: str
    installation_id: str | None
    scm_type: str


@dataclass
class StageDetail:
    node: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    findings_generated: int = 0


class AgentState(TypedDict):
    """LangGraph state for the observability analysis graph."""
    job_id: str
    tenant_id: str
    request: dict  # AnalysisRequest as dict
    repo_path: str | None
    changed_files: list[dict]  # list[ChangedFile] as dicts
    call_graph: dict | None
    coverage_map: dict | None
    dd_coverage: dict | None
    findings: list[dict]
    efficiency_scores: dict
    token_usage: dict
    messages: list[Any]
    error: str | None
    stage: str
    progress_pct: int
    repo_context: dict | None
    suppressed: list[dict]
    previous_job_id: str | None
    crossrun_summary: dict | None
    rag_context: str | None
    analysis_manifest: dict | None
    expansion_requested: list[str] | None
    expansion_count: int
