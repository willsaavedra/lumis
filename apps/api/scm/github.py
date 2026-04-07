"""GitHub App SCM adapter."""
from __future__ import annotations

import time
from pathlib import Path

import httpx
import jwt as pyjwt
import structlog

from apps.api.core.config import settings
from apps.api.core.redis_client import get_redis
from apps.api.core.security import verify_hmac_signature
from apps.api.scm.base import SCMAdapter
from apps.api.services.analysis_service import AnalysisRequest

log = structlog.get_logger(__name__)

GITHUB_API = "https://api.github.com"


def _read_github_app_private_key(path_str: str) -> str:
    """Load PEM from a file path, or from the first file inside a directory (K8s/docker secret mounts)."""
    p = Path(path_str)
    if p.is_file():
        return p.read_text()
    if p.is_dir():
        # e.g. Kubernetes mounts the secret as a directory with an arbitrary filename inside
        preferred = ("key", "private-key", "ssh-privatekey", "tls.key", "github_private_key.pem")
        for name in preferred:
            candidate = p / name
            if candidate.is_file():
                return candidate.read_text()
        files = sorted([x for x in p.iterdir() if x.is_file()])
        if not files:
            raise ValueError(f"GitHub App private key path is a directory with no files: {path_str}")
        return files[0].read_text()
    raise FileNotFoundError(f"GitHub App private key path not found: {path_str}")


class GitHubTokenManager:
    """Generate and cache GitHub App installation tokens."""

    async def get_installation_token(self, installation_id: int) -> str:
        """
        Get a fresh installation token, using Redis cache.
        Token is NEVER stored to DB or logs.
        """
        redis = get_redis()
        cache_key = f"gh_token:{installation_id}"
        cached = await redis.get(cache_key)
        if cached:
            return cached

        app_token = self._generate_app_jwt()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            data = response.json()

        token = data["token"]
        # Cache with TTL = expires_at - 5 minutes
        from datetime import datetime, timezone
        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        ttl = max(60, int((expires_at - datetime.now(timezone.utc)).total_seconds()) - 300)
        await redis.setex(cache_key, ttl, token)

        log.info("github_token_generated", installation_id=installation_id)
        return token

    def _generate_app_jwt(self) -> str:
        """Generate a short-lived JWT for GitHub App authentication."""
        if not settings.github_app_id or not settings.github_app_private_key_path:
            raise ValueError("GitHub App credentials not configured.")

        private_key = _read_github_app_private_key(settings.github_app_private_key_path)

        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 600,
            "iss": settings.github_app_id,
        }
        return pyjwt.encode(payload, private_key, algorithm="RS256")


class GitHubAdapter(SCMAdapter):
    def __init__(self) -> None:
        self.token_manager = GitHubTokenManager()

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        return verify_hmac_signature(payload, signature, settings.github_webhook_secret)

    def normalize_event(self, raw_payload: dict, event: str) -> AnalysisRequest | None:
        """Convert a GitHub webhook payload into a normalized AnalysisRequest."""
        if event != "pull_request":
            return None

        action = raw_payload.get("action")
        if action not in ("opened", "synchronize", "reopened"):
            return None

        pr = raw_payload.get("pull_request", {})
        repo = raw_payload.get("repository", {})
        installation = raw_payload.get("installation", {})

        # Get list of changed files from PR payload (limited; full list requires API call)
        changed_files: list[str] = []

        return AnalysisRequest(
            repo_full_name=repo.get("full_name", ""),
            scm_repo_id=str(repo.get("id", "")),
            scm_type="github",
            commit_sha=pr.get("head", {}).get("sha", ""),
            branch_ref=pr.get("head", {}).get("ref", "main"),
            pr_number=pr.get("number"),
            changed_files=changed_files,
            installation_id=str(installation.get("id", "")),
            trigger="pr",
        )

    async def clone_repo(self, installation_id: str, full_name: str, ref: str, target: Path) -> Path:
        """Clone repository using installation token."""
        token = await self.token_manager.get_installation_token(int(installation_id))
        clone_url = f"https://x-access-token:{token}@github.com/{full_name}.git"

        import subprocess
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, clone_url, str(target)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Git clone failed: {result.stderr}")

        return target

    async def get_changed_files(self, installation_id: str, full_name: str, pr_number: int) -> list[str]:
        """Fetch list of changed files in a PR."""
        token = await self.token_manager.get_installation_token(int(installation_id))
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GITHUB_API}/repos/{full_name}/pulls/{pr_number}/files",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                params={"per_page": 100},
            )
            response.raise_for_status()
            files = response.json()
        return [f["filename"] for f in files if f.get("status") != "removed"]

    async def post_report(
        self, installation_id: str, full_name: str, pr_number: int, report: str
    ) -> None:
        """Post analysis results as a PR review comment."""
        token = await self.token_manager.get_installation_token(int(installation_id))
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{GITHUB_API}/repos/{full_name}/issues/{pr_number}/comments",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"body": report},
            )

    async def list_refs(self, installation_id: str, full_name: str) -> dict[str, list[str]]:
        """List branches and tags for a repository."""
        token = await self.token_manager.get_installation_token(int(installation_id))
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            branches_resp = await client.get(
                f"{GITHUB_API}/repos/{full_name}/branches",
                headers=headers,
                params={"per_page": 100},
            )
            branches_resp.raise_for_status()
            tags_resp = await client.get(
                f"{GITHUB_API}/repos/{full_name}/tags",
                headers=headers,
                params={"per_page": 100},
            )
            tags_resp.raise_for_status()

        return {
            "branches": [b["name"] for b in branches_resp.json()],
            "tags": [t["name"] for t in tags_resp.json()],
        }

    async def get_contents(
        self,
        installation_id: str,
        full_name: str,
        *,
        path: str = "",
        ref: str,
    ) -> list[dict]:
        """
        List files and directories at a path (GitHub Contents API).
        Returns [{name, path, type: 'file'|'dir', size?}, ...]
        """
        from urllib.parse import quote

        token = await self.token_manager.get_installation_token(int(installation_id))
        path = path.strip().lstrip("/")
        if path:
            encoded = quote(path, safe="/")
            url = f"{GITHUB_API}/repos/{full_name}/contents/{encoded}"
        else:
            url = f"{GITHUB_API}/repos/{full_name}/contents"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params={"ref": ref}, timeout=30.0)
            response.raise_for_status()
            data = response.json()
        if isinstance(data, dict):
            # Single file
            return [
                {
                    "name": data.get("name", ""),
                    "path": data.get("path", path),
                    "type": "file" if data.get("type") == "file" else "dir",
                    "size": data.get("size"),
                }
            ]
        out = []
        for item in data:
            t = item.get("type")
            out.append(
                {
                    "name": item.get("name", ""),
                    "path": item.get("path", ""),
                    "type": "file" if t == "file" else "dir",
                    "size": item.get("size"),
                }
            )
        out.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))
        return out

    async def list_installation_repos(self, installation_id: int) -> list[dict]:
        """List all repos the GitHub App installation has access to."""
        token = await self.token_manager.get_installation_token(installation_id)
        repos: list[dict] = []
        page = 1
        per_page = 100
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            while True:
                response = await client.get(
                    f"{GITHUB_API}/installation/repositories",
                    headers=headers,
                    params={"per_page": per_page, "page": page},
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                batch = data.get("repositories") or []
                if not batch:
                    break
                repos.extend(batch)
                # GitHub may omit total_count; comparing len(repos) >= None raises TypeError (empty list bug).
                total_raw = data.get("total_count")
                if total_raw is not None and len(repos) >= int(total_raw):
                    break
                if len(batch) < per_page:
                    break
                page += 1

        log.info("github_list_installation_repos", installation_id=installation_id, count=len(repos))

        return [
            {
                "scm_repo_id": str(r["id"]),
                "full_name": r["full_name"],
                "default_branch": r.get("default_branch", "main"),
                "clone_url": r.get("clone_url"),
                "html_url": r.get("html_url"),
                "private": r.get("private", True),
            }
            for r in repos
        ]
