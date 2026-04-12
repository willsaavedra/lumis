"""Bitbucket Cloud OAuth + REST API 2.0."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx
import structlog
from opentelemetry.trace import StatusCode

from apps.api.core.config import settings
from apps.api.scm.base import SCMAdapter

log = structlog.get_logger(__name__)

API_ROOT = "https://api.bitbucket.org/2.0"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def exchange_oauth_code(code: str, redirect_uri: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://bitbucket.org/site/oauth2/access_token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            auth=(settings.bitbucket_client_id, settings.bitbucket_client_secret),
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()


async def fetch_current_user(token: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_ROOT}/user", headers=_headers(token), timeout=30.0)
        r.raise_for_status()
        return r.json()


async def list_repositories(token: str) -> list[dict]:
    """Repositories the user has access to."""
    out: list[dict] = []
    url: str | None = f"{API_ROOT}/repositories?role=member&pagelen=100"
    async with httpx.AsyncClient() as client:
        while url and len(out) < 2000:
            r = await client.get(url, headers=_headers(token), timeout=60.0)
            r.raise_for_status()
            data = r.json()
            for repo in data.get("values") or []:
                full = repo.get("full_name") or ""
                links = repo.get("links", {})
                clone_links = (links.get("clone") or []) if isinstance(links, dict) else []
                https_url = None
                for cl in clone_links:
                    if cl.get("name") == "https":
                        https_url = cl.get("href")
                        break
                if not https_url and clone_links:
                    https_url = clone_links[0].get("href")
                out.append(
                    {
                        "scm_repo_id": repo.get("uuid", full) or full,
                        "full_name": full,
                        "default_branch": (repo.get("mainbranch") or {}).get("name") or "main",
                        "clone_url": https_url,
                        "html_url": (links.get("html") or {}).get("href") if isinstance(links, dict) else None,
                        "private": repo.get("is_private", True),
                        "scm_type": "bitbucket",
                    }
                )
            url = None
            next_link = data.get("next")
            if isinstance(next_link, str):
                url = next_link
    return out


async def list_refs(token: str, full_name: str) -> dict[str, list[str]]:
    """full_name = workspace/slug"""
    parts = full_name.split("/")
    if len(parts) < 2:
        return {"branches": [], "tags": []}
    workspace, repo_slug = parts[0], parts[1]
    w = quote(workspace, safe="")
    s = quote(repo_slug, safe="")
    headers = _headers(token)
    async with httpx.AsyncClient() as client:
        br = await client.get(
            f"{API_ROOT}/repositories/{w}/{s}/refs/branches?pagelen=100",
            headers=headers,
            timeout=30.0,
        )
        br.raise_for_status()
        tr = await client.get(
            f"{API_ROOT}/repositories/{w}/{s}/refs/tags?pagelen=100",
            headers=headers,
            timeout=30.0,
        )
        tr.raise_for_status()
    bjson = br.json()
    tjson = tr.json()
    return {
        "branches": [b["name"] for b in bjson.get("values") or []],
        "tags": [t["name"] for t in tjson.get("values") or []],
    }


async def get_src_directory(
    token: str,
    full_name: str,
    *,
    path: str,
    ref: str,
) -> list[dict]:
    parts = full_name.split("/", 1)
    if len(parts) < 2:
        return []
    workspace, repo_slug = parts[0], parts[1]
    return await _list_src_via_api(token, workspace, repo_slug, ref, path)


async def _list_src_via_api(
    token: str,
    workspace: str,
    repo_slug: str,
    ref: str,
    path: str,
) -> list[dict]:
    """List files at path using Bitbucket file history / tree workaround."""
    from opentelemetry import trace
    
    tracer = trace.get_tracer(__name__)
    
    with tracer.start_as_current_span("bitbucket_list_src") as span:
        span.set_attribute("workspace", workspace)
        span.set_attribute("repo_slug", repo_slug)
        span.set_attribute("ref", ref)
        span.set_attribute("path", path)
        
        base = f"{API_ROOT}/repositories/{workspace}/{repo_slug}/src/{quote(ref, safe='')}"
        path = path.strip().lstrip("/")
        url = f"{base}/{path}" if path else f"{base}/"
        async with httpx.AsyncClient() as client:
            r = await client.get(
                url,
                headers={**_headers(token), "Accept": "application/json"},
                timeout=30.0,
            )
        if r.status_code != 200:
            return []
        try:
            payload = r.json()
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, str(exc))
            log.error("json_parse_failed", exc_info=True, workspace=workspace, repo_slug=repo_slug, ref=ref, path=path)
            return []
        if not isinstance(payload, list):
            return []
        out: list[dict] = []
        for node in payload:
            t = node.get("type")
            out.append(
                {
                    "name": node.get("path", "").split("/")[-1] or node.get("path", ""),
                    "path": node.get("path", ""),
                    "type": "dir" if t == "commit_directory" else "file",
                    "size": node.get("size"),
                }
            )
        out.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))
        return out


def authenticated_clone_url(token: str, clone_url: str | None, full_name: str) -> str:
    if clone_url and clone_url.startswith("https://"):
        from urllib.parse import urlparse

        u = urlparse(clone_url)
        netloc = u.netloc.split("@")[-1]
        path = u.path if u.path.endswith(".git") else u.path + ".git"
        return f"https://x-token-auth:{token}@{netloc}{path}"
    return f"https://x-token-auth:{token}@bitbucket.org/{full_name}.git"


class BitbucketAdapter(SCMAdapter):
    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        return False

    def normalize_event(self, raw_payload: dict, event: str) -> object | None:
        return None

    async def clone_repo(self, installation_id: str, full_name: str, ref: str, target: Path) -> Path:
        raise NotImplementedError

    async def get_changed_files(self, installation_id: str, full_name: str, pr_number: int) -> list[str]:
        raise NotImplementedError

    async def post_report(self, installation_id: str, full_name: str, pr_number: int, report: str) -> None:
        raise NotImplementedError

    async def list_installation_repos(self, installation_id: int) -> list[dict]:
        raise NotImplementedError
