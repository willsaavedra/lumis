"""Node: expand_context — autonomously fetch additional files requested by the LLM."""
from __future__ import annotations

from pathlib import Path

import structlog

from apps.agent.nodes.base import publish_progress, publish_thought
from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".java": "java",
    ".rs": "rust",
    ".cs": "csharp",
    ".rb": "ruby",
    ".tf": "terraform",
    ".hcl": "hcl",
}

_MAX_EXPANSION_FILES = 5
_MAX_FILE_CHARS = 30_000


def _detect_lang(file_path: str) -> str | None:
    ext = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return _EXT_TO_LANG.get(ext)


async def expand_context_node(state: AgentState) -> dict:
    """
    Read additional files from the cloned repo that the LLM requested
    via the `needs_more_context` field in its analysis output.
    """
    requested = state.get("expansion_requested") or []
    repo_path = state.get("repo_path")

    if not requested or not repo_path:
        return {"expansion_requested": None}

    await publish_progress(state, "expanding", 55, f"Fetching {len(requested)} additional files for deeper analysis...")

    existing_paths = {f["path"] for f in state.get("changed_files", []) if f.get("path")}
    new_files: list[dict] = []

    for rel_path in requested[:_MAX_EXPANSION_FILES]:
        if rel_path in existing_paths:
            continue
        abs_path = Path(repo_path) / rel_path
        if not abs_path.is_file():
            log.info("expand_context_file_not_found", path=rel_path, job_id=state.get("job_id"))
            continue
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")[:_MAX_FILE_CHARS]
            new_files.append({
                "path": rel_path,
                "content": content,
                "relevance_score": 2,
                "language": _detect_lang(rel_path),
                "source": "autonomous_expansion",
            })
        except Exception as e:
            log.warning("expand_context_read_failed", path=rel_path, error=str(e))

    log.info(
        "expand_context_complete",
        requested=len(requested),
        loaded=len(new_files),
        job_id=state.get("job_id"),
    )
    await publish_thought(
        state, "expand_context",
        f"Loaded {len(new_files)} additional files for re-analysis: {[f['path'] for f in new_files]}",
        status="done",
    )

    return {
        "changed_files": state["changed_files"] + new_files,
        "expansion_requested": None,
        "expansion_count": state.get("expansion_count", 0) + 1,
    }
