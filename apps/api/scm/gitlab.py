"""GitLab OAuth + REST API (api/v4)."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote  # used for project paths and ids

import httpx
import structlog

from apps.api.core.config import settings
from apps.api.scm.base import SCMAdapter

log = structlog.get_logger(__name__)


def _api_base() -> str:
    return settings.gitlab_base_url.rstrip("/") + "/api/v4"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def project_path_param(full_name: str) -> str:
    """URL-encode namespace/project for GitLab API path segment."""
    return quote(full_name, safe="")


async def exchange_oauth_code(code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for tokens."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{settings.gitlab_base_url.rstrip('/')}/oauth/token",
            data={
                "client_id": settings.gitlab_app_id,
                "client_secret": settings.gitlab_app_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()


async def fetch_current_user(token: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{_api_base()}/user", headers=_headers(token), timeout=30.0)
        r.raise_for_status()
        return r.json()


async def list_accessible_projects(token: str) -> list[dict]:
    """Projects the authenticated user has access to (for repo picker)."""
    out: list[dict] = []
    page = 1
    async with httpx.AsyncClient() as client:
        while page <= 50:
            r = await client.get(
                f"{_api_base()}/projects",
                headers=_headers(token),
                params={
                    "membership": "true",
                    "simple": "true",
                    "per_page": 100,
                    "page": page,
                    "order_by": "last_activity_at",
                },
                timeout=60.0,
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1

    return [
        {
            "scm_repo_id": str(p["id"]),
            "full_name": p["path_with_namespace"],
            "default_branch": p.get("default_branch") or "main",
            "clone_url": p.get("http_url_to_repo") or p.get("ssh_url_to_repo"),
            "html_url": p.get("web_url"),
            "private": p.get("visibility") != "public",
            "scm_type": "gitlab",
        }
        for p in out
    ]


async def list_refs(token: str, full_name: str) -> dict[str, list[str]]:
    enc = project_path_param(full_name)
    headers = _headers(token)
    async with httpx.AsyncClient() as client:
        br = await client.get(
            f"{_api_base()}/projects/{enc}/repository/branches",
            headers=headers,
            params={"per_page": 100},
            timeout=30.0,
        )
        br.raise_for_status()
        tr = await client.get(
            f"{_api_base()}/projects/{enc}/repository/tags",
            headers=headers,
            params={"per_page": 100},
            timeout=30.0,
        )
        tr.raise_for_status()
    return {
        "branches": [b["name"] for b in br.json()],
        "tags": [t["name"] for t in tr.json()],
    }


async def get_raw_file(token: str, full_name: str, file_path: str, ref: str) -> str | None:
    """Fetch raw file contents (e.g. README.md)."""
    enc = project_path_param(full_name)
    path_enc = quote(file_path.strip().lstrip("/"), safe="")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_api_base()}/projects/{enc}/repository/files/{path_enc}/raw",
            headers=_headers(token),
            params={"ref": ref},
            timeout=30.0,
        )
        if r.status_code != 200:
            return None
        return (r.text or "")[:8000]


async def get_tree(
    token: str,
    full_name: str,
    *,
    path: str = "",
    ref: str,
) -> list[dict]:
    enc = project_path_param(full_name)
    params: dict[str, str | int] = {"ref": ref, "per_page": 100}
    if path.strip():
        params["path"] = path.strip().lstrip("/")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_api_base()}/projects/{enc}/repository/tree",
            headers=_headers(token),
            params=params,
            timeout=30.0,
        )
        r.raise_for_status()
        data = r.json()
    out = []
    for item in data:
        t = item.get("type")
        out.append(
            {
                "name": item.get("name", ""),
                "path": item.get("path", ""),
                "type": "dir" if t == "tree" else "file",
                "size": item.get("size"),
            }
        )
    out.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))
    return out


def authenticated_clone_url(token: str, clone_url: str | None, full_name: str) -> str:
    """Insert OAuth token into HTTPS clone URL."""
    from urllib.parse import urlparse

    if clone_url and clone_url.startswith("http"):
        u = urlparse(clone_url)
        netloc = u.netloc.split("@")[-1]
        path = u.path if u.path.endswith(".git") else u.path + ".git"
        return f"https://oauth2:{token}@{netloc}{path}"
    host = settings.gitlab_base_url.replace("https://", "").replace("http://", "").rstrip("/").split("/")[0]
    return f"https://oauth2:{token}@{host}/{full_name}.git"


async def get_changed_files_for_mr(token: str, project_id: str, mr_iid: int) -> list[str]:
    enc = quote(str(project_id), safe="")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_api_base()}/projects/{enc}/merge_requests/{mr_iid}/changes",
            headers=_headers(token),
            timeout=30.0,
        )
        r.raise_for_status()
        data = r.json()
    changes = data.get("changes") or []
    return [c.get("new_path") or c.get("old_path") for c in changes if c.get("new_path") or c.get("old_path")]


class GitLabAdapter(SCMAdapter):
    """GitLab — webhooks and MR handling (partial)."""

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        from apps.api.core.config import settings as s

        return signature == s.gitlab_webhook_secret if s.gitlab_webhook_secret else False

    def normalize_event(self, raw_payload: dict, event: str) -> object | None:
        return None

    async def clone_repo(self, installation_id: str, full_name: str, ref: str, target: Path) -> Path:
        raise NotImplementedError("Use authenticated_clone_url from worker/agent")

    async def get_changed_files(self, installation_id: str, full_name: str, pr_number: int) -> list[str]:
        raise NotImplementedError

    async def post_report(self, installation_id: str, full_name: str, pr_number: int, report: str) -> None:
        raise NotImplementedError

    async def list_installation_repos(self, installation_id: int) -> list[dict]:
        raise NotImplementedError
