"""Node 6: Analyze observability efficiency issues."""
from __future__ import annotations

import re
import structlog

from apps.agent.nodes.base import publish_progress
from apps.agent.nodes.instrumentation_hints import (
    error_path_suggestion as _instr_error_suggestion,
    structured_log_suggestion as _instr_log_suggestion,
)
from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)

# High cardinality label patterns
HIGH_CARDINALITY_PATTERNS = [
    r'user_id\s*[:=]',
    r'trace_id\s*[:=]',
    r'request_id\s*[:=]',
    r'session_id\s*[:=]',
    r'transaction_id\s*[:=]',
]

# Unstructured log patterns
UNSTRUCTURED_LOG_PATTERNS = {
    "go": [r'fmt\.(?:Sprintf|Printf|Println|Print)', r'log\.(?:Print|Printf|Println)\('],
    "python": [r'print\(', r'logging\.(?:debug|info|warning|error)\(f["\']', r'logger\.(?:debug|info)\(f["\']'],
    "javascript": [r'console\.(?:log|warn|error|debug)\(', r'console\.log\(`'],
    "typescript": [r'console\.(?:log|warn|error|debug)\('],
}

# Debug log without sampling
DEBUG_LOG_HOTPATH = [
    r'for\s+\w+\s+:?=\s+range',  # Go for-range loop
    r'for\s+\w+\s+in\s+',         # Python for loop
    r'\.forEach\(',                 # JS forEach
    r'\.map\(',                     # JS map
]

# ---------------------------------------------------------------------------
# Error path detection: patterns that indicate an error/exception path
# paired with a check for whether RecordError/record_exception is absent
# ---------------------------------------------------------------------------
ERROR_PATH_PATTERNS: dict[str, list[str]] = {
    "go": [
        r'if\s+err\s*!=\s*nil\s*\{',   # canonical Go error check
        r'log\.Fatal\b',                 # unrecoverable without span
        r'\bpanic\(',                    # panic without span
    ],
    "python": [
        r'except\s+Exception\s*[:(]',   # broad exception catch
        r'except\s*:',                   # bare except
        r'except\s+\w+\s+as\s+\w+\s*:', # named exception catch
    ],
    "javascript": [
        r'\.catch\s*\(',                 # Promise .catch
        r'\bcatch\s*\(',                 # try/catch
    ],
    "typescript": [
        r'\.catch\s*\(',
        r'\bcatch\s*\(',
    ],
    "java": [
        r'\bcatch\s*\(',
        r'\.exceptionally\s*\(',         # CompletableFuture
    ],
}

# Patterns indicating error/exception recording IS present nearby
_RECORD_ERROR_PATTERNS = [
    r'span\.RecordError\b',
    r'span\.record_exception\b',
    r'recordException\b',
    r'RecordError\b',
    r'log\.Error\b',
    r'logger\.error\b',
    r'log\.error\b',
    r'structlog.*error',
    r'sentry\.CaptureException\b',
]

_WINDOW = 8  # lines to look ahead after error check for a record call


async def analyze_efficiency_node(state: AgentState) -> dict:
    """Detect observability efficiency issues via pattern matching."""
    await publish_progress(state, "analyzing", 65, "Analyzing observability efficiency...")

    findings: list[dict] = list(state.get("findings", []))
    files = [f for f in state["changed_files"] if f["relevance_score"] >= 1 and f.get("content")]

    # Pull instrumentation context so suggestions are vendor-consistent
    repo_context  = state.get("repo_context") or state.get("request", {})
    instrumentation = (repo_context.get("instrumentation") or "").strip().lower() or None

    for file_info in files:
        content = file_info.get("content", "")
        path = file_info["path"]
        lang = file_info.get("language", "")
        new_findings = _analyze_file_efficiency(content, path, lang, instrumentation)
        findings.extend(new_findings)

    log.info("efficiency_analysis_complete", total_findings=len(findings))
    await publish_progress(state, "analyzing", 70, f"Efficiency analysis complete: {len(findings)} findings.")
    return {"findings": findings}


def _analyze_file_efficiency(
    content: str,
    path: str,
    lang: str,
    instrumentation: str | None = None,
) -> list[dict]:
    findings = []
    lines = content.split("\n")

    # Check high cardinality labels
    for pattern in HIGH_CARDINALITY_PATTERNS:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line, re.IGNORECASE):
                if any(k in line.lower() for k in ("label", "tag", "metric", "counter", "gauge", "histogram")):
                    findings.append({
                        "pillar": "metrics",
                        "severity": "critical",
                        "dimension": "cost",
                        "title": "High cardinality metric label detected",
                        "description": "Using a high-cardinality value as a metric label will cause metric explosion and cost issues.",
                        "file_path": path,
                        "line_start": i,
                        "line_end": i,
                        "suggestion": "Use aggregate identifiers (user_tier, region) instead of unique IDs as metric labels.",
                        "estimated_monthly_cost_impact": 150.0,
                    })
                    break

    # Check unstructured logs — use vendor-aligned suggestion
    unstructured_patterns = UNSTRUCTURED_LOG_PATTERNS.get(lang, [])
    for pattern in unstructured_patterns:
        for i, line in enumerate(lines, 1):
            if re.search(pattern, line):
                findings.append({
                    "pillar": "logs",
                    "severity": "warning",
                    "dimension": "snr",
                    "title": "Unstructured log statement",
                    "description": "String-interpolated logs cannot be easily queried. Use structured logging (key=value pairs).",
                    "file_path": path,
                    "line_start": i,
                    "line_end": i,
                    "suggestion": _instr_log_suggestion(lang, instrumentation),
                    "estimated_monthly_cost_impact": 0.0,
                })
                break  # One finding per file for this pattern

    # Check N+1 span pattern (spans inside loops)
    _check_spans_in_loops(lines, path, lang, findings, instrumentation)

    # Check PII in logs
    _check_pii_in_logs(lines, path, lang, findings)

    # Check blind error paths (error catch/check without span RecordError)
    _check_blind_error_paths(lines, path, lang, findings, instrumentation)

    return findings


def _check_spans_in_loops(
    lines: list[str],
    path: str,
    lang: str,
    findings: list,
    instrumentation: str | None = None,
) -> None:
    use_dd = (instrumentation or "").strip().lower() == "datadog"
    parent_span_hint = (
        "Create a single parent dd-trace span before the loop, then use span events or tags inside each iteration."
        if use_dd else
        "Create a single parent OTEL span before the loop, then use span events or structured logs inside each iteration."
    )
    in_loop = False
    loop_start = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Detect loop entry
        if any(re.search(p, stripped) for p in DEBUG_LOG_HOTPATH):
            in_loop = True
            loop_start = i
        # Detect span creation inside loop
        if in_loop and any(k in stripped.lower() for k in ("startspan", "start_span", "tracer.start", "otel.span")):
            findings.append({
                "pillar": "traces",
                "severity": "warning",
                "dimension": "cost",
                "title": "N+1 span pattern: span created inside loop",
                "description": "Creating spans inside loops generates O(n) spans and can flood your tracing backend.",
                "file_path": path,
                "line_start": i,
                "line_end": i,
                "suggestion": parent_span_hint,
                "estimated_monthly_cost_impact": 80.0,
            })
            in_loop = False
        # Reset loop on dedent (simplified heuristic)
        if in_loop and i > loop_start + 50:
            in_loop = False


def _check_pii_in_logs(lines: list[str], path: str, lang: str, findings: list) -> None:
    pii_patterns = [r'\bemail\b', r'\bpassword\b', r'\bcpf\b', r'\btoken\b', r'\bcredit_card\b', r'\bssn\b']
    log_patterns = [r'log\.', r'logger\.', r'logging\.', r'console\.log', r'fmt\.Print', r'print\(']
    for i, line in enumerate(lines, 1):
        lower = line.lower()
        if any(re.search(lp, lower) for lp in log_patterns):
            if any(re.search(pp, lower) for pp in pii_patterns):
                findings.append({
                    "pillar": "logs",
                    "severity": "critical",
                    "dimension": "compliance",
                    "title": "Potential PII in log statement",
                    "description": "Logging PII fields (email, password, token, CPF) violates data protection regulations (LGPD, GDPR).",
                    "file_path": path,
                    "line_start": i,
                    "line_end": i,
                    "suggestion": "Remove PII from logs. Use hashed/masked identifiers or structured fields with PII scrubbing.",
                    "estimated_monthly_cost_impact": 0.0,
                })
                break


def _check_blind_error_paths(
    lines: list[str],
    path: str,
    lang: str,
    findings: list,
    instrumentation: str | None = None,
) -> None:
    """
    Detect error-handling blocks that have no span.RecordError / record_exception call.

    For each error pattern match we look at the next _WINDOW lines; if none of the
    _RECORD_ERROR_PATTERNS appear we emit a 'critical' finding on the error path.
    Uses instrumentation-aware suggestion so the snippet matches the declared vendor.
    """
    patterns = ERROR_PATH_PATTERNS.get(lang, [])
    if not patterns:
        return

    reported_lines: set[int] = set()

    for i, line in enumerate(lines):
        line_no = i + 1
        if line_no in reported_lines:
            continue

        for pattern in patterns:
            if re.search(pattern, line):
                window = "\n".join(lines[i: i + _WINDOW])
                has_record = any(re.search(rp, window) for rp in _RECORD_ERROR_PATTERNS)
                if not has_record:
                    findings.append({
                        "pillar": "traces",
                        "severity": "critical",
                        "dimension": "coverage",
                        "title": "Error path without span error recording or structured log",
                        "description": (
                            "An error/exception is caught or checked but neither "
                            "span error recording nor a structured error log "
                            "is called in the immediate block. This creates a blind spot in traces."
                        ),
                        "file_path": path,
                        "line_start": line_no,
                        "line_end": min(line_no + _WINDOW, len(lines)),
                        "suggestion": _instr_error_suggestion(lang, instrumentation),
                        "estimated_monthly_cost_impact": 0.0,
                        "confidence": "medium",
                    })
                    reported_lines.add(line_no)
                break  # avoid double-reporting the same line for multiple patterns


