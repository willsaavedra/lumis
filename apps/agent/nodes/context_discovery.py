"""Node: Context discovery — understand what the repo does and save to repository.context_summary."""
from __future__ import annotations

import shutil
from pathlib import Path

import structlog

from apps.agent.nodes.base import publish_progress
from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)

# Files that reveal what a project is
CONTEXT_FILES = [
    "README.md", "readme.md", "README.rst",
    "package.json", "pyproject.toml", "requirements.txt",
    "go.mod", "pom.xml", "build.gradle",
    "Dockerfile", "docker-compose.yml",
    "terraform.tf", "main.tf",
    ".github/workflows",
]

_MAX_FILE_BYTES = 6000

# Map file extensions to display language names
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "Python",
    ".go": "Go",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".rs": "Rust",
    ".cs": "C#",
    ".rb": "Ruby",
    ".tf": "Terraform",
    ".hcl": "Terraform",
}
_MIN_FILES = 3  # minimum files to consider a language present


def _detect_languages(repo: Path) -> list[str]:
    """Count source files per language; return those with meaningful presence."""
    counts: dict[str, int] = {}
    skip = {".git", "__pycache__", "node_modules", ".terraform", "vendor", "dist", "build"}
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        if any(s in p.parts for s in skip):
            continue
        lang = _EXT_TO_LANGUAGE.get(p.suffix.lower())
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return [lang for lang, count in sorted(counts.items(), key=lambda x: -x[1]) if count >= _MIN_FILES]


def _read_file(path: Path) -> str | None:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")[:_MAX_FILE_BYTES]
    except Exception:
        pass
    return None


def _collect_context_files(repo: Path) -> dict[str, str]:
    collected: dict[str, str] = {}
    for name in CONTEXT_FILES:
        p = repo / name
        if p.is_dir():
            # e.g. .github/workflows — grab first 3 yml files
            for yml in list(p.glob("*.yml"))[:3]:
                content = _read_file(yml)
                if content:
                    collected[str(yml.relative_to(repo))] = content
        else:
            content = _read_file(p)
            if content:
                collected[name] = content
    return collected


def _build_file_tree(repo: Path, max_entries: int = 80) -> str:
    lines = []
    for p in sorted(repo.rglob("*")):
        if any(skip in str(p) for skip in [".git", "__pycache__", "node_modules", ".terraform", "vendor/"]):
            continue
        if p.is_file():
            lines.append(str(p.relative_to(repo)))
        if len(lines) >= max_entries:
            lines.append("... (truncated)")
            break
    return "\n".join(lines)


async def context_discovery_node(state: AgentState) -> dict:
    """
    Read key repo files and generate a context summary using Claude.
    Saves the summary to repository.context_summary and marks the job complete.
    """
    await publish_progress(state, "discovering", 20, "Reading repository structure...")

    repo_path = state.get("repo_path")
    if not repo_path:
        await _mark_job_failed(state["job_id"], state["tenant_id"], "repo_path not set")
        return {"stage": "done", "progress_pct": 100}

    repo = Path(repo_path)
    context_files = _collect_context_files(repo)
    detected_languages = _detect_languages(repo)

    await publish_progress(state, "discovering", 50, "Analyzing repository context...")

    try:
        summary = await _generate_summary(state, context_files)
    except Exception as e:
        log.error("context_discovery_llm_failed", job_id=state["job_id"], error=str(e))
        summary = None

    await publish_progress(state, "discovering", 85, "Saving context...")

    if summary or detected_languages:
        await _save_context_summary(state["job_id"], state["tenant_id"], summary, detected_languages)

    # Cleanup
    shutil.rmtree(repo_path, ignore_errors=True)

    await publish_progress(state, "done", 100, "Context discovery complete!")
    log.info("context_discovery_complete", job_id=state["job_id"])
    return {"stage": "done", "progress_pct": 100}


async def _generate_summary(state: AgentState, context_files: dict[str, str]) -> str:
    from anthropic import Anthropic
    from apps.agent.core.config import settings

    client = Anthropic(api_key=settings.anthropic_api_key)

    files_section = "\n\n".join(
        f"### {name}\n```\n{content}\n```"
        for name, content in context_files.items()
    )

    request = state.get("request", {})
    repo_full_name = request.get("repo_full_name", "unknown")

    prompt = f"""Read the files below and write a single short paragraph (2-4 sentences) describing what this repository does.
Focus only on: what the service/project does, what language/framework it uses, and what type it is (API, worker, IaC, library, etc.).
Do not include headings, bullet points, or markdown. Plain text only. Do not invent details not present in the files.

Repository: {repo_full_name}

Key files:
{files_section if files_section else "(no key files found — use the repo name as a hint)"}"""

    message = client.messages.create(
        model=settings.anthropic_model_triage,  # use fast/cheap model
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


async def _save_context_summary(job_id: str, tenant_id: str, summary: str | None, detected_languages: list[str]) -> None:
    import uuid
    from sqlalchemy import select
    from apps.api.core.database import get_session_with_tenant
    from apps.api.models.analysis import AnalysisJob
    from apps.api.models.scm import Repository
    from datetime import datetime, timezone

    async with get_session_with_tenant(tenant_id) as session:
        job_result = await session.execute(
            select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id))
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return

        repo_result = await session.execute(
            select(Repository).where(Repository.id == job.repo_id)
        )
        repo = repo_result.scalar_one_or_none()
        if repo:
            if summary:
                repo.context_summary = summary
            repo.context_updated_at = datetime.now(timezone.utc)
            if detected_languages:
                # Merge: keep user-set languages + add newly detected ones
                existing = list(repo.language or [])
                merged = existing + [l for l in detected_languages if l not in existing]
                repo.language = merged

        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.credits_consumed = 0

    log.info("context_summary_saved", job_id=job_id, languages=detected_languages)


async def _mark_job_failed(job_id: str, tenant_id: str, reason: str) -> None:
    import uuid
    from sqlalchemy import select
    from apps.api.core.database import get_session_with_tenant
    from apps.api.models.analysis import AnalysisJob
    from datetime import datetime, timezone

    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id))
        )
        job = result.scalar_one_or_none()
        if job:
            job.status = "failed"
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = reason
