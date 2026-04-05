"""Node 1: Clone repository."""
from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

import structlog

from apps.agent.nodes.base import publish_progress
from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)


async def clone_repo_node(state: AgentState) -> dict:
    """Clone the repository (sparse checkout for PR diffs)."""
    job_id = state["job_id"]
    request = state["request"]

    await publish_progress(state, "cloning", 5, "Cloning repository...")

    repo_path = Path(f"/tmp/lumis-{job_id}")
    repo_path.mkdir(parents=True, exist_ok=True)

    try:
        clone_url = request["clone_url"]
        ref = request.get("ref", "main")
        installation_id = request.get("installation_id")
        scm_type = request.get("scm_type") or "github"
        repo_id = request.get("repo_id")

        # If GitHub App, get fresh token for clone URL
        if installation_id and scm_type == "github":
            try:
                from apps.api.scm.github import GitHubTokenManager
                token_manager = GitHubTokenManager()
                token = await token_manager.get_installation_token(int(installation_id))
                full_name = request["repo_full_name"]
                clone_url = f"https://x-access-token:{token}@github.com/{full_name}.git"
            except Exception as e:
                log.warning("token_fetch_failed_using_public_url", error=str(e))

        elif scm_type in ("gitlab", "bitbucket") and repo_id:
            try:
                from apps.api.core.database import AsyncSessionFactory
                from apps.api.core.security import decrypt_scm_token
                from apps.api.models.scm import Repository as RepoModel, ScmConnection
                from sqlalchemy import select

                async with AsyncSessionFactory() as session:
                    r = (
                        await session.execute(select(RepoModel).where(RepoModel.id == uuid.UUID(repo_id)))
                    ).scalar_one_or_none()
                    if r and r.scm_connection_id:
                        conn = (
                            await session.execute(
                                select(ScmConnection).where(ScmConnection.id == r.scm_connection_id)
                            )
                        ).scalar_one_or_none()
                        if conn and conn.encrypted_token:
                            raw = decrypt_scm_token(conn.encrypted_token)
                            if raw:
                                if scm_type == "gitlab":
                                    from apps.api.scm.gitlab import authenticated_clone_url

                                    clone_url = authenticated_clone_url(raw, clone_url, request["repo_full_name"])
                                else:
                                    from apps.api.scm.bitbucket import authenticated_clone_url as bb_auth

                                    clone_url = bb_auth(raw, clone_url, request["repo_full_name"])
            except Exception as e:
                log.warning("oauth_clone_url_failed", error=str(e), scm_type=scm_type)

        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, clone_url, str(repo_path)],
            capture_output=True, text=True, timeout=120,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Git clone failed: {result.stderr[:500]}")

        log.info("repo_cloned", job_id=job_id, path=str(repo_path))
        await publish_progress(state, "cloning", 10, "Repository cloned successfully.")
        return {"repo_path": str(repo_path)}

    except Exception as e:
        log.error("clone_failed", job_id=job_id, error=str(e))
        # Cleanup on failure
        shutil.rmtree(repo_path, ignore_errors=True)
        return {"repo_path": None, "error": str(e)}
