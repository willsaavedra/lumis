"""Node 2: Pre-triage using claude-haiku — classify file relevance cheaply."""
from __future__ import annotations

import json
import re

import structlog

from apps.agent.nodes.base import publish_progress
from apps.agent.schemas import AgentState, ChangedFile

log = structlog.get_logger(__name__)

# File patterns that are always irrelevant to observability
IRRELEVANT_PATTERNS = [
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".lock",
    ".png", ".jpg", ".svg", ".gif", ".ico",
    "_test.", "_spec.", ".test.", ".spec.",
    "generated", "proto", "vendor/", "node_modules/",
    ".css", ".scss", ".html", "migrations/",
]

# File extensions that are always relevant
RELEVANT_EXTENSIONS = [".go", ".py", ".java", ".ts", ".js", ".tf"]


def _quick_classify(file_path: str) -> int:
    """Heuristic classification before calling LLM — reduces token cost."""
    lower = file_path.lower()

    for pattern in IRRELEVANT_PATTERNS:
        if pattern in lower:
            return 0

    for ext in RELEVANT_EXTENSIONS:
        if lower.endswith(ext):
            return 1

    return 0


def _detect_language(file_path: str) -> str | None:
    ext_map = {
        ".go": "go",
        ".py": "python",
        ".java": "java",
        ".ts": "typescript",
        ".js": "javascript",
        ".tf": "terraform",
    }
    for ext, lang in ext_map.items():
        if file_path.endswith(ext):
            return lang
    return None


# Per-type file caps and minimum relevance score to load content
_TYPE_CONFIG: dict[str, dict] = {
    # Quick: only user-selected paths (API requires scope); expand dirs up to cap
    "quick":      {"file_cap": 250, "content_min_score": 2, "llm_classify": False},
    "full":       {"file_cap": 150, "content_min_score": 1, "llm_classify": True},
    # Deep codebase scan — high cap; worker walks src-like trees first
    "repository": {"file_cap": 8000, "content_min_score": 1, "llm_classify": True},
}

# Top-level dirs to walk first for repository-depth analysis (instrumentation lives here)
_PRIORITY_ROOT_DIRS = frozenset({
    "src", "lib", "pkg", "app", "internal", "cmd", "services", "packages",
    "server", "api", "backend", "handlers", "middleware", "components",
})

_SKIP_SEGMENTS = (".git", "__pycache__", "node_modules", "vendor/", "dist/", "build/", ".venv", "venv/")


def _path_should_skip(rel_posix: str) -> bool:
    lower = rel_posix.lower()
    return any(seg in lower for seg in _SKIP_SEGMENTS)


def _expand_repo_roots(repo_root, roots: list[str], *, max_files: int) -> list[str]:
    """
    Expand a list of file paths and/or directory roots to a flat list of file paths
    relative to the repository root (posix).
    """
    from pathlib import Path

    repo_root = Path(repo_root)
    out: list[str] = []
    seen: set[str] = set()

    for raw in roots:
        r = (raw or "").strip().replace("\\", "/").lstrip("/")
        if not r:
            continue
        full = (repo_root / r).resolve()
        try:
            full.relative_to(repo_root.resolve())
        except ValueError:
            continue
        if full.is_file():
            rel = str(full.relative_to(repo_root)).replace("\\", "/")
            if rel not in seen and not _path_should_skip(rel):
                seen.add(rel)
                out.append(rel)
                if len(out) >= max_files:
                    return out
        elif full.is_dir():
            for f in sorted(full.rglob("*")):
                if not f.is_file():
                    continue
                rel = str(f.relative_to(repo_root)).replace("\\", "/")
                if _path_should_skip(rel):
                    continue
                if rel not in seen:
                    seen.add(rel)
                    out.append(rel)
                    if len(out) >= max_files:
                        return out
    return out


def _walk_whole_repo(repo_root, *, max_files: int) -> list[str]:
    from pathlib import Path

    repo_root = Path(repo_root)
    out: list[str] = []
    for f in sorted(repo_root.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(repo_root)).replace("\\", "/")
        if _path_should_skip(rel):
            continue
        out.append(rel)
        if len(out) >= max_files:
            break
    return out


def _walk_repo_prioritized(repo_root, *, max_files: int) -> list[str]:
    """
    Deep codebase scan: enumerate likely application source trees first (src/, cmd/, …),
    then the remainder. Same skip rules as full walk.
    """
    from pathlib import Path

    repo_root = Path(repo_root)
    out: list[str] = []
    seen: set[str] = set()

    def try_add(rel: str) -> bool:
        if rel in seen or _path_should_skip(rel):
            return False
        seen.add(rel)
        out.append(rel)
        return True

    for dirname in sorted(_PRIORITY_ROOT_DIRS):
        if len(out) >= max_files:
            return out
        d = repo_root / dirname
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*")):
            if len(out) >= max_files:
                return out
            if not f.is_file():
                continue
            rel = str(f.relative_to(repo_root)).replace("\\", "/")
            try_add(rel)

    for f in sorted(repo_root.rglob("*")):
        if len(out) >= max_files:
            break
        if not f.is_file():
            continue
        rel = str(f.relative_to(repo_root)).replace("\\", "/")
        try_add(rel)

    return out


async def pre_triage_node(state: AgentState) -> dict:
    """
    Classify changed files by observability relevance.
      - quick:      user-selected paths only (required via API); all expanded files analyzed
      - full:       whole repo (or optional path scope), LLM classification for ambiguous files
      - repository: prioritized deep walk (src/, cmd/, … first), then rest; LLM classification
    """
    await publish_progress(state, "triaging", 15, "Classifying changed files...")

    request = state["request"]
    analysis_type = request.get("analysis_type", "full")
    cfg = _TYPE_CONFIG.get(analysis_type, _TYPE_CONFIG["full"])

    requested = list(request.get("changed_files") or [])
    repo_path = state.get("repo_path")
    raw_files: list[str] = []

    if repo_path:
        if requested:
            raw_files = _expand_repo_roots(repo_path, requested, max_files=cfg["file_cap"])
            if not raw_files:
                log.warning(
                    "scope_paths_expanded_empty",
                    requested=requested,
                    job_id=state.get("job_id"),
                )
        elif analysis_type == "quick":
            raw_files = []
            log.warning(
                "quick_analysis_missing_scope",
                job_id=state.get("job_id"),
            )
        elif analysis_type == "repository":
            raw_files = _walk_repo_prioritized(repo_path, max_files=cfg["file_cap"])
        else:
            raw_files = _walk_whole_repo(repo_path, max_files=cfg["file_cap"])

    # Cap total files
    raw_files = raw_files[:cfg["file_cap"]]

    classified: list[dict] = []
    for file_path in raw_files:
        score = _quick_classify(file_path)
        classified.append({
            "path": file_path,
            "language": _detect_language(file_path),
            "relevance_score": score,
            "content": None,
        })

    # Quick runs only on user-selected scope — treat every expanded file as in-scope for analysis
    if analysis_type == "quick" and requested:
        for f in classified:
            f["relevance_score"] = 2

    # LLM classification for ambiguous files (only for full / repository)
    ambiguous = [f for f in classified if f["relevance_score"] == 1]
    llm_succeeded = False
    if cfg["llm_classify"] and ambiguous and len(ambiguous) <= 40:
        try:
            classified = await _llm_classify(classified, ambiguous, state)
            llm_succeeded = True
        except Exception as e:
            log.warning("haiku_triage_failed_using_heuristics", error=str(e))

    # If LLM unavailable or skipped, promote score-1 files so they still get analyzed
    if not llm_succeeded:
        for f in classified:
            if f["relevance_score"] == 1:
                f["relevance_score"] = 2

    # Load content for files that meet the minimum relevance threshold
    min_score = cfg["content_min_score"]
    if state.get("repo_path"):
        from pathlib import Path
        repo = Path(state["repo_path"])
        for f in classified:
            if f["relevance_score"] >= min_score:
                try:
                    content_path = repo / f["path"]
                    if content_path.exists():
                        f["content"] = content_path.read_text(encoding="utf-8", errors="replace")[:8000]
                except Exception:
                    pass

    relevant_count = sum(1 for f in classified if f["relevance_score"] >= min_score and f.get("content"))

    # Scan loaded files for lumis-ignore comments
    suppressed = _scan_lumis_ignore(classified)
    if suppressed:
        log.info("lumis_ignore_found", count=len(suppressed), job_id=state["job_id"])

    log.info(
        "triage_complete",
        analysis_type=analysis_type,
        total=len(classified),
        relevant=relevant_count,
        job_id=state["job_id"],
    )
    await publish_progress(state, "triaging", 20, f"Found {relevant_count} relevant files.")

    return {"changed_files": classified, "suppressed": suppressed}


def _scan_lumis_ignore(files: list[dict]) -> list[dict]:
    """
    Scan file contents for lumis-ignore annotations.
    Supports:
      - // lumis-ignore   (Go, JS, TS, Java)
      - # lumis-ignore    (Python, Terraform)
    Returns a list of {"file_path": str, "line": int} dicts.
    """
    suppressed: list[dict] = []
    for f in files:
        content = f.get("content")
        if not content:
            continue
        for line_no, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.endswith("// lumis-ignore") or stripped.endswith("# lumis-ignore"):
                suppressed.append({"file_path": f["path"], "line": line_no + 1})
    return suppressed


async def _llm_classify(
    all_files: list[dict],
    ambiguous: list[dict],
    state: AgentState,
) -> list[dict]:
    """Use Haiku to classify ambiguous files."""
    from anthropic import Anthropic
    from apps.agent.core.config import settings

    client = Anthropic(api_key=settings.anthropic_api_key)
    file_list = "\n".join(f"- {f['path']}" for f in ambiguous)

    message = client.messages.create(
        model=settings.anthropic_model_triage,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""Classify each file by observability relevance (0=irrelevant, 1=low, 2=high).
High relevance: business logic, HTTP handlers, DB calls, queue consumers, error handling.
Low relevance: utilities, helpers, configs.
Irrelevant: tests, assets, generated code, docs.

Files:
{file_list}

Reply with ONLY a JSON array, no explanation: [{{"path": "...", "score": 0|1|2}}, ...]""",
            },
            {"role": "assistant", "content": "["},
        ],
    )

    raw = "[" + message.content[0].text
    # Extract the first complete JSON array from the response
    match = re.search(r'\[.*?\]', raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array in response: {raw[:200]}")
    scores = json.loads(match.group())
    score_map = {s["path"]: s["score"] for s in scores}

    for f in all_files:
        if f["path"] in score_map:
            f["relevance_score"] = score_map[f["path"]]

    return all_files
