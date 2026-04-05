"""Service: generate code fixes with Claude and open a GitHub PR."""
from __future__ import annotations

import difflib
import subprocess
import uuid
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


def actionable_findings_for_fix_pr(findings: list) -> list:
    """
    Same rules as the PR pipeline: observability pillars only, critical/warning, with file path.
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


# Keywords that indicate an observability-related line.
# A changed hunk must contain at least one of these to be kept.
_OTEL_KEYWORDS = [
    "opentelemetry", "otel", "otlp",
    "prometheus", "prometheus_client",
    "metric", "counter", "gauge", "histogram", "summary",
    "meter", "instrument",
    "structlog", "logger", "logging",
    "span", "trace", "tracer", "tracing",
    "observe", "record", "emit",
    "datadog", "statsd", "sentry",
    "baggage", "context.with",
    "start_span", "startspan", "end_span",
    "set_attribute", "add_event",
]


def _is_observability_line(line: str) -> bool:
    lower = line.lower()
    return any(kw in lower for kw in _OTEL_KEYWORDS)


def _filter_to_observability_hunks(original: str, fixed: str) -> str | None:
    """
    Compares original and fixed using SequenceMatcher.
    Rules per hunk type:
    - equal:   keep as-is
    - delete:  ALWAYS revert (never remove lines — even if they contain OTel keywords,
               Claude may have deleted them because the file was truncated)
    - insert:  accept only if the added lines are OTel-related
    - replace: accept only if the NEW lines are OTel-related AND the hunk does not
               shrink by more than 20% (guards against truncation-caused rewrites)
    Returns None if no observability changes survive.
    """
    orig_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, orig_lines, fixed_lines, autojunk=False)
    result: list[str] = []
    has_otel_change = False

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        orig_hunk = orig_lines[i1:i2]
        fixed_hunk = fixed_lines[j1:j2]

        if tag == "equal":
            result.extend(orig_hunk)

        elif tag == "delete":
            # Never accept pure deletions — always restore original lines.
            result.extend(orig_hunk)

        elif tag == "insert":
            # Accept only if the added lines are OTel-related.
            if any(_is_observability_line(ln) for ln in fixed_hunk):
                result.extend(fixed_hunk)
                has_otel_change = True
            # else: discard the insertion entirely

        elif tag == "replace":
            # Accept only if:
            # 1. The replacement contains OTel-related lines, AND
            # 2. The replacement doesn't shrink the hunk significantly
            #    (a big shrink = Claude truncated the file and rewrote less)
            size_ok = len(fixed_hunk) >= len(orig_hunk) * 0.8
            if size_ok and any(_is_observability_line(ln) for ln in fixed_hunk):
                result.extend(fixed_hunk)
                has_otel_change = True
            else:
                log.debug(
                    "non_otel_or_shrinking_hunk_reverted",
                    orig_size=len(orig_hunk),
                    fixed_size=len(fixed_hunk),
                )
                result.extend(orig_hunk)

    # Final size guard: if result is still <85% of original, something went wrong.
    if len(result) < len(orig_lines) * 0.85:
        log.warning(
            "fixed_file_too_short_rejecting",
            orig_lines=len(orig_lines),
            result_lines=len(result),
        )
        return None

    return "".join(result) if has_otel_change else None


async def create_fix_pr(job_id: str) -> str:
    """
    1. Load analysis job + findings from DB
    2. Clone repo with GitHub App token
    3. For each finding with file_path, generate full-file patch via Claude Sonnet
    4. Strip any non-observability changes from the patch
    5. Apply patches, create branch, push, open PR
    Returns the PR URL.
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

        findings = (await session.execute(
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

    actionable = actionable_findings_for_fix_pr(list(findings))

    if not actionable:
        raise ValueError("No actionable observability findings with file paths to fix")

    installation_id = connection.installation_id if connection else None
    repo_path = await _clone(repo, installation_id, job_id)

    try:
        by_file: dict[str, list] = {}
        for f in actionable:
            by_file.setdefault(f.file_path, []).append(f)

        branch = f"lumis/fix-{job_id[:8]}"
        _git(repo_path, ["checkout", "-b", branch])

        changed_files: list[str] = []
        reverted_files: list[str] = []

        for file_path, file_findings in by_file.items():
            full_path = repo_path / file_path
            if not full_path.exists():
                continue

            original = full_path.read_text(encoding="utf-8", errors="replace")
            raw_fixed = await _generate_fixed_file(original, file_path, file_findings)

            if not raw_fixed or raw_fixed.strip() == original.strip():
                log.info("file_unchanged_by_claude", file=file_path)
                continue

            # Strip any hunks that don't touch observability code
            safe_fixed = _filter_to_observability_hunks(original, raw_fixed)
            if safe_fixed is None:
                log.warning("all_hunks_non_otel_reverted", file=file_path)
                reverted_files.append(file_path)
                continue

            full_path.write_text(safe_fixed, encoding="utf-8")
            changed_files.append(file_path)
            log.info("file_patched", file=file_path, job_id=job_id)

        if not changed_files:
            raise ValueError(
                "No observability changes survived validation. "
                f"Reverted files: {reverted_files or 'none generated'}"
            )

        _git(repo_path, ["add"] + changed_files)
        _git(repo_path, [
            "commit", "-m",
            f"fix(observability): apply Lumis recommendations [{job_id[:8]}]\n\n"
            f"Auto-generated by Lumis agent. Fixes {len(changed_files)} file(s):\n"
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
            changed_files=changed_files,
            findings=actionable,
        )

        log.info("fix_pr_created", pr_url=pr_url, job_id=job_id)
        return pr_url

    finally:
        import shutil
        shutil.rmtree(repo_path, ignore_errors=True)


async def _clone(repo, installation_id: str | None, job_id: str) -> Path:
    from apps.api.scm.github import GitHubTokenManager

    repo_path = Path(f"/tmp/lumis-fix-{job_id}")
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

    _git(repo_path, ["config", "user.email", "lumis-bot@lumis.dev"])
    _git(repo_path, ["config", "user.name", "Lumis Bot"])

    return repo_path


def _git(cwd: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git"] + args, cwd=str(cwd),
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr[:300]}")
    return result.stdout


async def _generate_fixed_file(
    original: str,
    file_path: str,
    findings: list,
) -> str:
    """Ask Claude Sonnet to return the complete fixed file."""
    from anthropic import AsyncAnthropic
    from apps.api.core.config import settings

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    findings_desc = "\n".join(
        f"- Line {f.line_start}: [{f.severity.upper()}] {f.title}\n"
        f"  Problem: {f.description}\n"
        f"  Suggestion: {f.suggestion or 'Apply OTel best practice'}"
        for f in findings
    )

    ext = Path(file_path).suffix
    lang_map = {".py": "python", ".go": "go", ".ts": "typescript", ".js": "javascript", ".java": "java"}
    lang = lang_map.get(ext, "code")

    # Safety: refuse to rewrite files over 60k chars — too large to return completely
    # and truncation causes mass deletions. Skip them; the filter will log the skip.
    if len(original) > 60000:
        log.warning("file_too_large_skipping_fix", file=file_path, chars=len(original))
        return None

    message = await client.messages.create(
        model=settings.anthropic_model_primary,
        max_tokens=8000,
        system=f"""You are an expert SRE engineer fixing observability issues in {lang}.

TASK: Fix ONLY the listed observability issues. Return the complete file.

STRICTLY FORBIDDEN — do NOT change any of the following:
- Business logic, algorithms, or data transformations
- Function signatures, class names, or variable names
- Imports unrelated to observability (metrics, logging, tracing)
- Code formatting, indentation style, or whitespace
- Comments or docstrings unrelated to the fix
- Error handling, retries, or timeout logic
- Configuration values or constants unrelated to instrumentation
- Any line that is not directly required by the listed findings

ALLOWED changes:
- Adding OpenTelemetry SDK imports and instrumentation
- Adding/fixing metric counter, gauge, or histogram declarations
- Adding/fixing span creation and attribute setting
- Converting unstructured logs to structured key=value format
- Adding trace context propagation to existing calls
- Fixing high-cardinality metric labels

Use OpenTelemetry SDK (vendor-neutral). Return ONLY the complete file — no explanations, no markdown fences.""",
        messages=[{
            "role": "user",
            "content": f"""Fix the following observability issues in this {lang} file.

FILE: {file_path}

ISSUES TO FIX (observability only):
{findings_desc}

ORIGINAL FILE:
{original}

Return the complete fixed file. Touch only what is needed for the listed issues.""",
        }],
    )

    fixed = message.content[0].text.strip()
    if fixed.startswith("```"):
        lines = fixed.split("\n")
        fixed = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    return fixed


async def _open_pr(
    installation_id: str | None,
    full_name: str,
    branch: str,
    base: str,
    job_id: str,
    changed_files: list[str],
    findings: list,
) -> str:
    import httpx
    from apps.api.scm.github import GitHubTokenManager

    token = await GitHubTokenManager().get_installation_token(int(installation_id)) if installation_id else None
    if not token:
        raise ValueError("No GitHub token available to open PR")

    critical = sum(1 for f in findings if f.severity == "critical")
    warning = sum(1 for f in findings if f.severity == "warning")

    pillar_counts: dict[str, int] = {}
    for f in findings:
        pillar_counts[f.pillar] = pillar_counts.get(f.pillar, 0) + 1

    pillar_rows = "\n".join(f"| {p.capitalize()} | {c} |" for p, c in pillar_counts.items())

    body = f"""## Lumis Observability Fix

This PR was auto-generated by the [Lumis](https://lumis.dev) observability agent.
Only observability-related code was modified (metrics, logs, traces instrumentation).
No business logic was changed.

### Findings addressed

| Severity | Count |
|----------|-------|
| Critical | {critical} |
| Warning  | {warning} |

| Pillar | Findings |
|--------|----------|
{pillar_rows}

### Files changed
{chr(10).join(f"- `{f}`" for f in changed_files)}

### Details
{chr(10).join(f"- **{f.title}** (`{f.file_path}:{f.line_start}`)" for f in findings)}

---
*Review carefully before merging. Job ID: `{job_id}`*
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
                "title": f"fix(observability): Lumis recommendations [{job_id[:8]}]",
                "body": body,
                "head": branch,
                "base": base,
            },
        )
        resp.raise_for_status()
        return resp.json()["html_url"]
