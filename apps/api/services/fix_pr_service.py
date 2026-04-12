"""Service: generate code fixes and open a GitHub PR using analysis findings."""
from __future__ import annotations

import difflib
import json
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python", ".go": "go", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".java": "java", ".rs": "rust",
    ".rb": "ruby", ".cs": "csharp",
}


# ---------------------------------------------------------------------------
# Public helpers (used by API router to decide eligibility)
# ---------------------------------------------------------------------------

def actionable_findings_for_fix_pr(findings: list) -> list:
    """
    Observability pillars only, critical/warning, with file path.
    Accepts ORM Finding rows or dicts (e.g. from JSONB).
    """
    out: list = []
    for f in findings:
        if isinstance(f, dict):
            fp = f.get("file_path")
            sev = f.get("severity")
            pil = f.get("pillar")
        else:
            fp = getattr(f, "file_path", None)
            sev = getattr(f, "severity", None)
            pil = getattr(f, "pillar", None)
        if not fp:
            continue
        if sev not in ("critical", "warning"):
            continue
        if pil not in ("metrics", "logs", "traces"):
            continue
        out.append(f)
    return out


def has_recommendations_for_fix_pr(job: object) -> bool:
    """True if this analysis has at least one finding that can drive a fix PR."""
    result = getattr(job, "result", None)
    if not result:
        return False
    rows = getattr(result, "findings_list", None)
    if rows is not None:
        lst = list(rows)
        if lst and len(actionable_findings_for_fix_pr(lst)) > 0:
            return True
    raw = getattr(result, "findings", None)
    if isinstance(raw, list) and raw:
        return len(actionable_findings_for_fix_pr(raw)) > 0
    return False


# ---------------------------------------------------------------------------
# Enriched finding — fuses ORM columns with JSONB code snippets
# ---------------------------------------------------------------------------

@dataclass
class EnrichedFinding:
    id: str
    pillar: str
    severity: str
    title: str
    description: str
    file_path: str
    line_start: int | None
    line_end: int | None
    suggestion: str | None
    code_before: str | None = None
    code_after: str | None = None


async def _load_enriched_findings(job_id: str) -> tuple[list[EnrichedFinding], object, object, object]:
    """
    Load ORM Finding rows + JSONB code_before/code_after, repo, and connection.
    Returns (enriched_findings, job, repo, connection).
    """
    from sqlalchemy import select
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob, AnalysisResult, Finding
    from apps.api.models.scm import Repository, ScmConnection

    async with AsyncSessionFactory() as session:
        job = (await session.execute(
            select(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id))
        )).scalar_one_or_none()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        result = (await session.execute(
            select(AnalysisResult).where(AnalysisResult.job_id == uuid.UUID(job_id))
        )).scalar_one_or_none()

        orm_findings = (await session.execute(
            select(Finding).where(Finding.result_id == result.id)
        )).scalars().all() if result else []

        repo = (await session.execute(
            select(Repository).where(Repository.id == job.repo_id)
        )).scalar_one_or_none()

        connection = None
        if repo and repo.scm_connection_id:
            connection = (await session.execute(
                select(ScmConnection).where(ScmConnection.id == repo.scm_connection_id)
            )).scalar_one_or_none()

    if not repo:
        raise ValueError("Repository not found")

    jsonb_list = result.findings if result and isinstance(result.findings, list) else []
    jsonb_by_id: dict[str, dict] = {str(f["id"]): f for f in jsonb_list if f.get("id")}

    actionable_orm = actionable_findings_for_fix_pr(list(orm_findings))
    if not actionable_orm:
        raise ValueError("No actionable observability findings with file paths to fix")

    enriched: list[EnrichedFinding] = []
    for f in actionable_orm:
        extra = jsonb_by_id.get(str(f.id), {})
        enriched.append(EnrichedFinding(
            id=str(f.id),
            pillar=f.pillar,
            severity=f.severity,
            title=f.title,
            description=f.description,
            file_path=f.file_path,
            line_start=f.line_start,
            line_end=f.line_end,
            suggestion=f.suggestion,
            code_before=extra.get("code_before"),
            code_after=extra.get("code_after"),
        ))

    return enriched, job, repo, connection


# ---------------------------------------------------------------------------
# Snippet patching — surgical code_before → code_after replacement
# ---------------------------------------------------------------------------

def _apply_snippet_patch(original: str, code_before: str, code_after: str) -> str | None:
    """
    Apply a single code_before → code_after patch.
    Returns the patched file content, or None if the snippet can't be located.
    """
    if not code_before or not code_after:
        return None

    before_stripped = code_before.strip()
    after_stripped = code_after.strip()

    if not before_stripped:
        return None

    if before_stripped in original:
        return original.replace(before_stripped, after_stripped, 1)

    orig_lines = original.splitlines()
    before_lines = before_stripped.splitlines()

    if not before_lines:
        return None

    best_ratio = 0.0
    best_start = -1
    window = len(before_lines)

    for start in range(len(orig_lines) - window + 1):
        candidate = "\n".join(orig_lines[start:start + window])
        ratio = difflib.SequenceMatcher(None, before_stripped, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = start

    if best_ratio >= 0.80 and best_start >= 0:
        patched_lines = orig_lines[:best_start] + after_stripped.splitlines() + orig_lines[best_start + window:]
        return "\n".join(patched_lines)

    return None


# ---------------------------------------------------------------------------
# RAG retrieval for fix context
# ---------------------------------------------------------------------------

async def _retrieve_rag_for_file(
    repo_id: str,
    file_path: str,
    pillar: str,
    language: str | None,
    tenant_id: str | None,
) -> str:
    """Retrieve top-K RAG chunks relevant to fixing a specific file. Returns formatted text."""
    try:
        from apps.api.core.config import settings
        if not settings.openai_api_key:
            return ""

        from apps.agent.tasks.rag_shared import embed_texts

        queries = [
            f"previous findings {repo_id} {file_path}",
        ]
        if language:
            queries.append(f"{language} {pillar} observability instrumentation best practice")
            queries.append(f"{language} span trace error handling structured logging")

        embeddings = await embed_texts(queries)
        query_embeddings = list(zip(queries, embeddings))
        chunks = await _search_rag_index(query_embeddings, tenant_id=tenant_id, language=language)

        if not chunks:
            return ""

        lines = ["### Relevant context from knowledge base:\n"]
        total = 0
        for c in chunks[:5]:
            text = c["content"].strip()
            if total + len(text) > 4000:
                break
            lines.append(text)
            lines.append("")
            total += len(text)

        return "\n".join(lines) if len(lines) > 2 else ""
    except Exception as e:
        log.warning("fix_pr_rag_retrieval_failed", error=str(e))
        return ""


async def _search_rag_index(
    query_embeddings: list[tuple[str, list[float]]],
    *,
    tenant_id: str | None,
    language: str | None,
) -> list[dict]:
    """Search knowledge_chunks for fix-relevant context."""
    from sqlalchemy import text
    from apps.api.core.database import AsyncSessionFactory

    results: list[dict] = []
    seen: set[str] = set()

    async with AsyncSessionFactory() as session:
        if tenant_id:
            await session.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))

        for query, embedding in query_embeddings:
            embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
            lang_filter = "AND language = :language" if language else ""
            tenant_filter = (
                "AND (tenant_id IS NULL OR tenant_id = CAST(:tenant_id AS uuid))"
                if tenant_id else "AND tenant_id IS NULL"
            )

            sql = text(f"""
                SELECT content, source_type,
                       1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM knowledge_chunks
                WHERE (expires_at IS NULL OR expires_at > now())
                      {tenant_filter} {lang_filter}
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT 5
            """)
            params: dict = {"embedding": embedding_str, "limit": 5}
            if language:
                params["language"] = language
            if tenant_id:
                params["tenant_id"] = tenant_id

            rows = (await session.execute(sql, params)).fetchall()
            for row in rows:
                sim = float(row.similarity)
                if sim < 0.30:
                    continue
                key = row.content[:100]
                if key not in seen:
                    seen.add(key)
                    results.append({"content": row.content, "source_type": row.source_type, "similarity": sim})

    return sorted(results, key=lambda c: c["similarity"], reverse=True)


# ---------------------------------------------------------------------------
# Focused LLM fix — fallback when snippet patch fails
# ---------------------------------------------------------------------------

async def _generate_focused_fix(
    original: str,
    file_path: str,
    findings: list[EnrichedFinding],
    repo_context: dict,
    rag_context: str,
    llm_provider: str = "anthropic",
) -> list[dict]:
    """
    Ask the LLM for targeted snippet fixes (not full-file rewrite).
    Returns list of {"code_before": ..., "code_after": ...} dicts.
    """
    from apps.agent.llm.chat_completion import chat_complete
    from apps.api.core.config import settings

    ext = Path(file_path).suffix
    lang = _EXT_TO_LANG.get(ext, "code")

    if len(original) > 60000:
        log.warning("file_too_large_skipping_fix", file=file_path, chars=len(original))
        return []

    context_summary = (repo_context.get("context_summary") or "")[:500]
    instrumentation = repo_context.get("instrumentation") or "opentelemetry"
    obs_backend = repo_context.get("observability_backend") or "unknown"

    findings_desc = "\n".join(
        f"- Line {f.line_start or '?'}: [{f.severity.upper()}] {f.title}\n"
        f"  Problem: {f.description}\n"
        f"  Suggestion: {f.suggestion or 'Apply observability best practice'}\n"
        f"  Original code: {f.code_before or '(not available)'}"
        for f in findings
    )

    region_start = min((f.line_start or 1) for f in findings)
    region_end = max((f.line_end or f.line_start or 1) for f in findings)
    context_start = max(0, region_start - 20)
    context_end = min(len(original.splitlines()), region_end + 20)
    region_lines = original.splitlines()[context_start:context_end]
    region_text = "\n".join(f"{context_start + i + 1:4d}| {line}" for i, line in enumerate(region_lines))

    if llm_provider == "cerebra_ai":
        model = settings.cerebra_ai_model_primary
    else:
        model = settings.anthropic_model_primary

    system_prompt = f"""You are an expert SRE engineer fixing observability issues in {lang}.

Repository: {context_summary}
Instrumentation stack: {instrumentation} | Backend: {obs_backend}

{rag_context}

Return ONLY a JSON array of fixes. Each fix object:
[{{"code_before": "exact lines from the file", "code_after": "corrected version"}}]

Rules:
- code_before MUST be a verbatim excerpt from the file (2-10 lines)
- code_after MUST be syntactically correct, production-ready {lang}
- Fix ONLY the listed observability issues — do NOT touch business logic
- Use {instrumentation} SDK patterns (not vendor-specific unless the project already uses it)
- Keep snippets concise — only the changed region plus minimal surrounding context"""

    user_prompt = f"""Fix these observability issues in {file_path}:

ISSUES:
{findings_desc}

RELEVANT FILE REGION (lines {context_start + 1}-{context_end}):
{region_text}

Return ONLY the JSON array of fixes — no markdown fences, no explanations."""

    try:
        resp = await chat_complete(
            system=system_prompt,
            user=user_prompt,
            model=model,
            max_tokens=2000,
            provider=llm_provider,
            base_url=settings.cerebra_ai_base_url,
            api_key=settings.anthropic_api_key if llm_provider == "anthropic" else settings.cerebra_ai_api_key,
            temperature=settings.cerebra_ai_temperature if llm_provider == "cerebra_ai" else 0.3,
            top_p=settings.cerebra_ai_top_p if llm_provider == "cerebra_ai" else 0.9,
            timeout=settings.cerebra_ai_timeout if llm_provider == "cerebra_ai" else 120,
        )

        raw = resp.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        fixes = json.loads(raw)
        if isinstance(fixes, list):
            return [
                f for f in fixes
                if isinstance(f, dict) and f.get("code_before") and f.get("code_after")
            ]
    except Exception as e:
        log.warning("focused_fix_llm_failed", file=file_path, error=str(e))

    return []


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git(cwd: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git"] + args, cwd=str(cwd),
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr[:300]}")
    return result.stdout


async def _clone(repo, installation_id: str | None, job_id: str) -> Path:
    from apps.api.scm.github import GitHubTokenManager

    repo_path = Path(f"/tmp/horion-fix-{job_id}")
    repo_path.mkdir(parents=True, exist_ok=True)

    clone_url = repo.clone_url or f"https://github.com/{repo.full_name}.git"

    if installation_id:
        token = await GitHubTokenManager().get_installation_token(int(installation_id))
        clone_url = f"https://x-access-token:{token}@github.com/{repo.full_name}.git"

    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", repo.default_branch, clone_url, str(repo_path)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Clone failed: {result.stderr[:400]}")

    _git(repo_path, ["config", "user.email", "bot@horion.pro"])
    _git(repo_path, ["config", "user.name", "Horion Bot"])

    return repo_path


# ---------------------------------------------------------------------------
# PR creation with rich body
# ---------------------------------------------------------------------------

@dataclass
class FilePatchResult:
    file_path: str
    findings: list[EnrichedFinding]
    patches_applied: list[dict] = field(default_factory=list)
    method: str = "skipped"


async def _open_pr(
    installation_id: str | None,
    full_name: str,
    branch: str,
    base: str,
    job_id: str,
    patch_results: list[FilePatchResult],
) -> str:
    import httpx
    from apps.api.scm.github import GitHubTokenManager

    token = await GitHubTokenManager().get_installation_token(int(installation_id)) if installation_id else None
    if not token:
        raise ValueError("No GitHub token available to open PR")

    all_findings = [f for pr in patch_results for f in pr.findings]
    critical = sum(1 for f in all_findings if f.severity == "critical")
    warning = sum(1 for f in all_findings if f.severity == "warning")

    pillar_counts: dict[str, int] = {}
    for f in all_findings:
        pillar_counts[f.pillar] = pillar_counts.get(f.pillar, 0) + 1
    pillar_rows = "\n".join(f"| {p.capitalize()} | {c} |" for p, c in pillar_counts.items())

    files_section_parts: list[str] = []
    for pr in patch_results:
        count = len(pr.findings)
        files_section_parts.append(f"\n### `{pr.file_path}` — {count} finding{'s' if count != 1 else ''}\n")
        for f in pr.findings:
            files_section_parts.append(f"**[{f.severity.upper()}] {f.title}**")
            files_section_parts.append(f"> {f.description}\n")
            cb = f.code_before
            ca = f.code_after
            if cb and ca:
                diff_lines = []
                for line in cb.strip().splitlines():
                    diff_lines.append(f"- {line}")
                for line in ca.strip().splitlines():
                    diff_lines.append(f"+ {line}")
                files_section_parts.append("```diff\n" + "\n".join(diff_lines) + "\n```\n")
            elif f.suggestion:
                files_section_parts.append(f"*Suggestion:* {f.suggestion}\n")

    files_detail = "\n".join(files_section_parts)
    changed_files = [pr.file_path for pr in patch_results]

    body = f"""## Horion Observability Fix

This PR was auto-generated by the [Horion](https://horion.pro) reliability engineering agent.
Only observability-related code was modified (metrics, logs, traces instrumentation).
No business logic was changed.

### Summary

| Severity | Count |
|----------|-------|
| Critical | {critical} |
| Warning  | {warning} |

| Pillar | Findings |
|--------|----------|
{pillar_rows}

### Files changed
{chr(10).join(f"- `{f}`" for f in changed_files)}

### Changes detail
{files_detail}
---
*Review carefully before merging. Generated by [horion.pro](https://horion.pro) — Job `{job_id[:8]}`*
"""

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/repos/{full_name}/pulls",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "title": f"fix(observability): Horion recommendations [{job_id[:8]}]",
                "body": body,
                "head": branch,
                "base": base,
            },
        )
        resp.raise_for_status()
        return resp.json()["html_url"]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def create_fix_pr(job_id: str) -> str:
    """
    1. Load enriched findings (ORM + JSONB code snippets)
    2. Clone repo
    3. For each file: try snippet patch, fallback to focused LLM fix
    4. Commit, push, open PR
    Returns the PR URL.
    """
    enriched, job, repo, connection = await _load_enriched_findings(job_id)
    installation_id = connection.installation_id if connection else None

    repo_context: dict = {}
    try:
        repo_context = {
            "context_summary": getattr(repo, "context_summary", None),
            "instrumentation": getattr(repo, "instrumentation", None),
            "observability_backend": getattr(repo, "observability_backend", None),
            "language": getattr(repo, "language", None),
            "app_map": getattr(repo, "app_map", None),
        }
    except Exception:
        pass

    repo_path = await _clone(repo, installation_id, job_id)
    llm_provider = getattr(job, "llm_provider", "anthropic") or "anthropic"
    tenant_id = str(job.tenant_id)

    try:
        by_file: dict[str, list[EnrichedFinding]] = {}
        for f in enriched:
            by_file.setdefault(f.file_path, []).append(f)

        branch = f"horion/fix-{job_id[:8]}"
        _git(repo_path, ["checkout", "-b", branch])

        patch_results: list[FilePatchResult] = []
        changed_files: list[str] = []
        skipped_files: list[str] = []

        for file_path, file_findings in by_file.items():
            full_path = repo_path / file_path
            if not full_path.exists():
                log.info("fix_pr_file_not_found", file=file_path)
                skipped_files.append(file_path)
                continue

            original = full_path.read_text(encoding="utf-8", errors="replace")
            current = original
            pr = FilePatchResult(file_path=file_path, findings=file_findings)
            patched_any = False

            findings_needing_llm: list[EnrichedFinding] = []

            for finding in file_findings:
                if finding.code_before and finding.code_after:
                    result = _apply_snippet_patch(current, finding.code_before, finding.code_after)
                    if result is not None:
                        current = result
                        pr.patches_applied.append({"finding_id": finding.id, "method": "snippet_patch"})
                        patched_any = True
                        log.info("snippet_patch_applied", file=file_path, finding=finding.title)
                        continue

                findings_needing_llm.append(finding)

            if findings_needing_llm:
                lang_list = repo_context.get("language") or []
                primary_lang = lang_list[0].lower() if isinstance(lang_list, list) and lang_list else None
                pillar = file_findings[0].pillar

                rag_context = await _retrieve_rag_for_file(
                    repo_id=str(repo.id),
                    file_path=file_path,
                    pillar=pillar,
                    language=primary_lang,
                    tenant_id=tenant_id,
                )

                llm_fixes = await _generate_focused_fix(
                    current, file_path, findings_needing_llm,
                    repo_context, rag_context, llm_provider,
                )

                for fix in llm_fixes:
                    fix_result = _apply_snippet_patch(current, fix["code_before"], fix["code_after"])
                    if fix_result is not None:
                        current = fix_result
                        pr.patches_applied.append({"method": "focused_llm"})
                        patched_any = True
                        log.info("focused_fix_applied", file=file_path)

            if patched_any and current != original:
                full_path.write_text(current, encoding="utf-8")
                changed_files.append(file_path)
                pr.method = "patched"
                patch_results.append(pr)
                log.info("file_patched", file=file_path, job_id=job_id, patches=len(pr.patches_applied))
            else:
                skipped_files.append(file_path)
                log.info("file_skipped_no_patches", file=file_path)

        if not changed_files:
            raise ValueError(
                f"No files were patched. Skipped: {skipped_files or 'none'}. "
                "Snippet patches could not be applied and LLM fallback did not produce usable fixes."
            )

        _git(repo_path, ["add"] + changed_files)
        _git(repo_path, [
            "commit", "-m",
            f"fix(observability): apply Horion recommendations [{job_id[:8]}]\n\n"
            f"Auto-generated by Horion agent. Fixes {len(changed_files)} file(s):\n"
            + "\n".join(f"- {f}" for f in changed_files),
        ])

        token = None
        if installation_id:
            from apps.api.scm.github import GitHubTokenManager
            token = await GitHubTokenManager().get_installation_token(int(installation_id))

        remote = f"https://x-access-token:{token}@github.com/{repo.full_name}.git" if token else repo.clone_url
        _git(repo_path, ["remote", "set-url", "origin", remote])
        _git(repo_path, ["push", "origin", branch])

        pr_url = await _open_pr(
            installation_id=installation_id,
            full_name=repo.full_name,
            branch=branch,
            base=repo.default_branch,
            job_id=job_id,
            patch_results=patch_results,
        )

        log.info("fix_pr_created", pr_url=pr_url, job_id=job_id, files=len(changed_files))
        return pr_url

    finally:
        import shutil
        shutil.rmtree(repo_path, ignore_errors=True)
