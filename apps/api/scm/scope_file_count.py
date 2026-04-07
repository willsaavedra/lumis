"""Count blob (file) paths under user-selected repo paths for cost estimation."""
from __future__ import annotations

from urllib.parse import quote

import httpx
import structlog

from apps.api.models.scm import Repository, ScmConnection

log = structlog.get_logger(__name__)

GITHUB_API = "https://api.github.com"


def _norm(p: str) -> str:
    return (p or "").strip().lstrip("/").replace("\\", "/")


def _blob_in_scopes(blob_path: str, scopes: list[str]) -> bool:
    """True if blob_path is exactly a selected file or under a selected folder."""
    bp = _norm(blob_path)
    for s in scopes:
        s = _norm(s)
        if not s:
            continue
        if bp == s:
            return True
        if bp.startswith(s + "/"):
            return True
    return False


async def count_files_github_installation(
    installation_id: str,
    full_name: str,
    ref: str,
    scopes: list[str],
) -> int | None:
    """Use Git recursive tree API; returns None on failure."""
    from apps.api.scm.github import GitHubAdapter

    if not scopes:
        return 0

    adapter = GitHubAdapter()
    token = await adapter.token_manager.get_installation_token(int(installation_id))
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient() as client:
            cr = await client.get(
                f"{GITHUB_API}/repos/{full_name}/commits",
                headers=headers,
                params={"sha": ref.strip(), "per_page": 1},
                timeout=45.0,
            )
            cr.raise_for_status()
            commits = cr.json()
            if not commits:
                return None
            tree_sha = commits[0].get("commit", {}).get("tree", {}).get("sha")
            if not tree_sha:
                return None

            tr = await client.get(
                f"{GITHUB_API}/repos/{full_name}/git/trees/{tree_sha}",
                headers=headers,
                params={"recursive": "1"},
                timeout=90.0,
            )
            tr.raise_for_status()
            data = tr.json()
    except Exception as e:
        log.warning("github_scope_file_count_failed", repo=full_name, error=str(e))
        return None

    if data.get("truncated"):
        log.warning("github_tree_truncated", repo=full_name)

    entries = data.get("tree") or []
    matched = 0
    for e in entries:
        if e.get("type") != "blob":
            continue
        p = e.get("path") or ""
        if _blob_in_scopes(p, scopes):
            matched += 1

    if matched == 0 and len(scopes) > 0:
        return max(1, len(scopes))
    return matched


async def _gitlab_tree_page(
    token: str,
    enc_project: str,
    *,
    path: str,
    ref: str,
    page: int,
    recursive: bool,
) -> list[dict]:
    from apps.api.scm.gitlab import _api_base, _headers

    params: dict[str, str | int | bool] = {
        "ref": ref,
        "per_page": 100,
        "page": page,
        "recursive": recursive,
    }
    if path.strip():
        params["path"] = path.strip().lstrip("/")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_api_base()}/projects/{enc_project}/repository/tree",
            headers=_headers(token),
            params=params,
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []


async def count_files_gitlab_token(
    token: str,
    full_name: str,
    ref: str,
    scopes: list[str],
) -> int | None:
    """Paginated recursive tree per scope path; union blob paths."""
    from apps.api.scm.gitlab import project_path_param

    if not scopes:
        return 0

    enc = project_path_param(full_name)
    seen: set[str] = set()

    try:
        for scope in scopes:
            sp = _norm(scope)
            page = 1
            while True:
                items = await _gitlab_tree_page(
                    token, enc, path=sp, ref=ref.strip(), page=page, recursive=True
                )
                if not items:
                    break
                for item in items:
                    if item.get("type") == "blob":
                        p = item.get("path") or ""
                        if p:
                            seen.add(p)
                if len(items) < 100:
                    break
                page += 1
    except Exception as e:
        log.warning("gitlab_scope_file_count_failed", repo=full_name, error=str(e))
        return None

    if not seen:
        return max(1, len(scopes))
    return len(seen)


async def _bitbucket_collect_files(
    token: str,
    full_name: str,
    ref: str,
    path: str,
    out: set[str],
    *,
    depth: int = 0,
    max_depth: int = 32,
) -> None:
    from apps.api.scm import bitbucket as bb

    if depth > max_depth:
        return
    items = await bb.get_src_directory(token, full_name, path=path, ref=ref)
    for item in items:
        t = item.get("type")
        p = item.get("path") or ""
        if not p:
            continue
        if t == "file":
            out.add(p)
        elif t == "dir":
            await _bitbucket_collect_files(token, full_name, ref, p, out, depth=depth + 1, max_depth=max_depth)


async def count_files_bitbucket_token(
    token: str,
    full_name: str,
    ref: str,
    scopes: list[str],
) -> int | None:
    if not scopes:
        return 0
    seen: set[str] = set()
    try:
        for scope in scopes:
            sp = _norm(scope)
            await _bitbucket_collect_files(token, full_name, ref, sp, seen)
        return max(len(seen), 1) if seen else max(1, len(scopes))
    except Exception as e:
        log.warning("bitbucket_scope_file_count_failed", repo=full_name, error=str(e))
        return None


async def count_files_in_repo_scope(
    repo: Repository,
    connection: ScmConnection | None,
    ref: str,
    paths: list[str],
) -> int | None:
    """
    Resolve how many files will be analyzed for the given path selections.
    Returns None if counting failed (caller should fall back to len(paths)).
    """
    norm_paths = [p for p in paths if p and str(p).strip()]
    if not norm_paths:
        return None

    if not connection:
        return None

    ref = (ref or "main").strip()
    full_name = repo.full_name

    try:
        if connection.scm_type == "github" and connection.installation_id:
            return await count_files_github_installation(
                str(connection.installation_id),
                full_name,
                ref,
                norm_paths,
            )
        if connection.scm_type == "gitlab":
            from apps.api.core.security import decrypt_scm_token

            token = decrypt_scm_token(connection.encrypted_token)
            if not token:
                return None
            return await count_files_gitlab_token(token, full_name, ref, norm_paths)
        if connection.scm_type == "bitbucket":
            from apps.api.core.security import decrypt_scm_token

            token = decrypt_scm_token(connection.encrypted_token)
            if not token:
                return None
            return await count_files_bitbucket_token(token, full_name, ref, norm_paths)
    except Exception as e:
        log.warning("scope_file_count_dispatch_failed", repo=full_name, error=str(e))
        return None

    return None
