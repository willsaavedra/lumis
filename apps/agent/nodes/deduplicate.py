"""Node: Deduplicate findings by fingerprint and filter lumis-ignore suppressions."""
from __future__ import annotations

import structlog

from apps.agent.nodes.base import publish_progress, publish_thought
from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)

_SEVERITY_ORDER = {"critical": 3, "warning": 2, "info": 1}


def _fingerprint(finding: dict) -> str:
    """Stable fingerprint for a finding — used for dedup and cross-run diff."""
    pillar = finding.get("pillar", "")
    file_path = finding.get("file_path") or ""
    line = finding.get("line_start")
    try:
        line_part = str(int(line)) if line is not None else ""
    except (TypeError, ValueError):
        line_part = ""
    title = (finding.get("title") or "")[:50]
    return f"{pillar}:{file_path}:{line_part}:{title}"


def _higher_severity(a: dict, b: dict) -> dict:
    """Return whichever finding has the higher severity."""
    return a if _SEVERITY_ORDER.get(a.get("severity", "info"), 1) >= _SEVERITY_ORDER.get(b.get("severity", "info"), 1) else b


async def deduplicate_node(state: AgentState) -> dict:
    """
    Deduplicate findings by fingerprint (keep highest severity per group)
    and suppress any that are covered by a lumis-ignore comment in the source.
    """
    await publish_progress(state, "deduplicating", 72, "Deduplicating findings...", stage_index=7)

    findings: list[dict] = list(state.get("findings", []))
    suppressed: list[dict] = state.get("suppressed", [])

    # Build a suppression lookup: (file_path, line) → True
    suppression_set: set[tuple[str, int]] = {
        (s["file_path"], s["line"]) for s in suppressed
    }

    # Dedup by fingerprint — keep highest severity
    seen: dict[str, dict] = {}
    for finding in findings:
        fp = _fingerprint(finding)
        if fp in seen:
            seen[fp] = _higher_severity(seen[fp], finding)
        else:
            seen[fp] = finding

    deduped = list(seen.values())
    dedup_count = len(findings) - len(deduped)

    # Apply lumis-ignore suppressions
    if suppression_set:
        filtered = []
        suppressed_count = 0
        for finding in deduped:
            f_path = finding.get("file_path") or ""
            f_line = finding.get("line_start")
            if f_line and (f_path, f_line) in suppression_set:
                suppressed_count += 1
                log.info(
                    "finding_suppressed_by_lumis_ignore",
                    file_path=f_path,
                    line=f_line,
                    title=finding.get("title"),
                )
            else:
                filtered.append(finding)
        deduped = filtered
        if suppressed_count:
            log.info("lumis_ignore_suppressed", count=suppressed_count)

    log.info(
        "deduplication_complete",
        original=len(findings),
        after_dedup=len(deduped),
        merged=dedup_count,
        job_id=state.get("job_id"),
    )
    await publish_thought(
        state, "deduplicate",
        f"Merged {dedup_count} duplicates — {len(deduped)} unique findings remain",
        status="done",
    )
    await publish_progress(state, "deduplicating", 73, f"Deduplicated to {len(deduped)} findings.", stage_index=7)
    return {"findings": deduped}
