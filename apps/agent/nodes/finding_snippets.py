"""Fill missing code_before from line ranges using changed_files or cloned repo."""
from __future__ import annotations

from pathlib import Path

import structlog

from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)


def _normalize_rel_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _build_changed_files_content_map(state: AgentState) -> dict[str, str]:
    """path -> full file text from analysis snapshot (PR/changed files)."""
    m: dict[str, str] = {}
    for f in state.get("changed_files") or []:
        p = f.get("path")
        if not p:
            continue
        c = f.get("content") or ""
        m[_normalize_rel_path(p)] = c
        m[p] = c
    return m


def _read_file_text_from_repo(repo_path: str | None, file_path: str) -> str | None:
    if not repo_path:
        return None
    base = Path(repo_path)
    for rel in (_normalize_rel_path(file_path), file_path):
        full = base / rel
        try:
            return full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return None


def _get_file_text_for_finding(
    content_map: dict[str, str],
    repo_path: str | None,
    file_path: str,
) -> str | None:
    n = _normalize_rel_path(file_path)
    if n in content_map and content_map[n].strip():
        return content_map[n]
    if file_path in content_map and content_map[file_path].strip():
        return content_map[file_path]
    return _read_file_text_from_repo(repo_path, file_path)


def _lines_slice(text: str, line_start: int | None, line_end: int | None) -> str | None:
    if line_start is None or line_start < 1:
        return None
    lines = text.replace("\r\n", "\n").split("\n")
    end = line_end if line_end is not None else line_start
    if end < line_start:
        end = line_start
    i0 = line_start - 1
    i1 = min(len(lines), end)
    if i0 >= len(lines) or i0 >= i1:
        return None
    return "\n".join(lines[i0:i1])


def enrich_finding_code_snippets(
    finding: dict,
    content_map: dict[str, str],
    repo_path: str | None,
) -> None:
    """
    Ensure code_before exists when we have a line range: LLMs often omit it.

    Uses changed_files content first, then the cloned repo on disk.
    """
    fp = finding.get("file_path")
    ls = finding.get("line_start")
    if not fp or ls is None:
        return
    before = finding.get("code_before")
    if isinstance(before, str) and before.strip():
        return
    text = _get_file_text_for_finding(content_map, repo_path, fp)
    if not text:
        return
    le = finding.get("line_end")
    snippet = _lines_slice(text, ls, le)
    if snippet and snippet.strip():
        finding["code_before"] = snippet
        log.debug(
            "finding_code_before_enriched",
            file_path=fp,
            line_start=ls,
            line_end=le,
        )


def enrich_findings_code_snippets(findings: list[dict], state: AgentState) -> None:
    """Run snippet enrichment for every finding before persisting."""
    content_map = _build_changed_files_content_map(state)
    repo_path = state.get("repo_path")
    for f in findings:
        enrich_finding_code_snippets(f, content_map, repo_path)
