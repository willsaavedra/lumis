"""Repository management endpoints."""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from apps.api.core.database import get_session_with_tenant
from apps.api.core.deps import CurrentUser
from apps.api.models.analysis import AnalysisJob
from apps.api.models.scm import Repository
from apps.api.scm.repo_web_url import repo_web_url

log = structlog.get_logger(__name__)
router = APIRouter()
tracer = trace.get_tracer(__name__)


class RepoResponse(BaseModel):
    id: str
    full_name: str
    web_url: str
    default_branch: str
    is_active: bool
    schedule_enabled: bool
    schedule_cron: str
    created_at: str
    scm_type: str
    repo_type: str | None = None
    app_subtype: str | None = None
    iac_provider: str | None = None
    language: list[str] | None = None
    observability_backend: str | None = None
    instrumentation: str | None = None
    obs_metadata: dict | None = None
    context_summary: str | None = None
    last_analysis_at: str | None = None


class ActivateRepoRequest(BaseModel):
    scm_repo_id: str
    full_name: str
    default_branch: str = "main"
    clone_url: str | None = None
    scm_type: str = "github"
    repo_type: str | None = None
    app_subtype: str | None = None
    iac_provider: str | None = None
    language: list[str] | None = None
    observability_backend: str | None = None
    instrumentation: str | None = None
    obs_metadata: dict | None = None


@router.get("", response_model=list[RepoResponse])
async def list_repositories(current: CurrentUser) -> list[RepoResponse]:
    user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        last_completed_at = (
            select(func.max(AnalysisJob.completed_at))
            .where(
                AnalysisJob.tenant_id == uuid.UUID(tenant_id),
                AnalysisJob.repo_id == Repository.id,
                AnalysisJob.status == "completed",
            )
            .correlate(Repository)
            .scalar_subquery()
        )
        result = await session.execute(
            select(Repository, last_completed_at.label("last_analysis_at"))
            .where(Repository.tenant_id == uuid.UUID(tenant_id), Repository.is_active == True)
            .options(selectinload(Repository.connection))
        )
        rows = result.all()
    return [_repo_to_response(repo, last_analysis_at) for (repo, last_analysis_at) in rows]


@router.get("/available")
async def list_available_repositories(current: CurrentUser) -> list[dict]:
    """List repos from all connected SCM providers (GitHub App, GitLab OAuth, Bitbucket OAuth)."""
    user, tenant_id, _ = current
    from apps.api.scm.github import GitHubAdapter
    from apps.api.core.database import get_session_with_tenant
    from apps.api.core.security import decrypt_scm_token
    from apps.api.models.scm import ScmConnection
    from apps.api.scm import gitlab as gitlab_scm
    from apps.api.scm import bitbucket as bitbucket_scm

    async with get_session_with_tenant(tenant_id) as session:
        conn_result = await session.execute(
            select(ScmConnection).where(ScmConnection.tenant_id == uuid.UUID(tenant_id))
        )
        connections = conn_result.scalars().all()

    combined: list[dict] = []
    for connection in connections:
        try:
            if connection.scm_type == "github" and connection.installation_id:
                adapter = GitHubAdapter()
                repos = await adapter.list_installation_repos(int(connection.installation_id))
                for r in repos:
                    r["scm_type"] = "github"
                combined.extend(repos)
            elif connection.scm_type == "gitlab":
                token = decrypt_scm_token(connection.encrypted_token)
                if token:
                    combined.extend(await gitlab_scm.list_accessible_projects(token))
            elif connection.scm_type == "bitbucket":
                token = decrypt_scm_token(connection.encrypted_token)
                if token:
                    combined.extend(await bitbucket_scm.list_repositories(token))
        except Exception as e:
            log.error(
                "list_available_repos_failed",
                error=str(e),
                tenant_id=tenant_id,
                scm_type=connection.scm_type,
                installation_id=getattr(connection, "installation_id", None),
                exc_info=True,
            )
    return combined


@router.get("/{repo_id}", response_model=RepoResponse)
async def get_repository(repo_id: str, current: CurrentUser) -> RepoResponse:
    """Return a single active repository with last completed analysis timestamp."""
    user, tenant_id, _ = current
    try:
        rid = uuid.UUID(repo_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid repo_id.") from e
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(Repository)
            .where(
                Repository.tenant_id == uuid.UUID(tenant_id),
                Repository.id == rid,
                Repository.is_active == True,
            )
            .options(selectinload(Repository.connection))
        )
        repo = result.scalar_one_or_none()
        if not repo:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
        last_at = await _get_last_analysis_at(session, tenant_id, rid)
    return _repo_to_response(repo, last_at)


@router.post("", response_model=RepoResponse, status_code=status.HTTP_201_CREATED)
async def activate_repository(body: ActivateRepoRequest, current: CurrentUser) -> RepoResponse:
    user, tenant_id, _ = current
    from apps.api.models.scm import ScmConnection
    async with get_session_with_tenant(tenant_id) as session:
        conn_result = await session.execute(
            select(ScmConnection).where(
                ScmConnection.tenant_id == uuid.UUID(tenant_id),
                ScmConnection.scm_type == body.scm_type,
            )
        )
        connection = conn_result.scalar_one_or_none()
        if body.scm_type in ("gitlab", "bitbucket") and not connection:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Connect {body.scm_type} in Settings → Connections before adding repositories.",
            )

        existing = await session.execute(
            select(Repository).where(
                Repository.tenant_id == uuid.UUID(tenant_id),
                Repository.scm_repo_id == body.scm_repo_id,
            )
        )
        repo = existing.scalar_one_or_none()
        if not repo:
            repo = Repository(
                tenant_id=uuid.UUID(tenant_id),
                scm_repo_id=body.scm_repo_id,
                full_name=body.full_name,
                default_branch=body.default_branch,
                clone_url=body.clone_url,
                is_active=True,
                scm_connection_id=connection.id if connection else None,
                repo_type=body.repo_type,
                app_subtype=body.app_subtype,
                iac_provider=body.iac_provider,
                language=body.language,
                observability_backend=body.observability_backend,
                instrumentation=body.instrumentation,
                obs_metadata=body.obs_metadata,
            )
            session.add(repo)
        else:
            repo.is_active = True
            if connection and not repo.scm_connection_id:
                repo.scm_connection_id = connection.id
            if body.repo_type is not None:
                repo.repo_type = body.repo_type
            if body.app_subtype is not None:
                repo.app_subtype = body.app_subtype
            if body.iac_provider is not None:
                repo.iac_provider = body.iac_provider
            if body.language is not None:
                repo.language = body.language
            if body.observability_backend is not None:
                repo.observability_backend = body.observability_backend
            if body.instrumentation is not None:
                repo.instrumentation = body.instrumentation
            if body.obs_metadata is not None:
                repo.obs_metadata = body.obs_metadata
        await session.flush()
        refreshed = await session.execute(
            select(Repository)
            .where(Repository.id == repo.id)
            .options(selectinload(Repository.connection))
        )
        repo = refreshed.scalar_one()
        last_analysis_at = await _get_last_analysis_at(session, tenant_id, repo.id)
    return _repo_to_response(repo, last_analysis_at)


@router.post("/{repo_id}/activate", response_model=RepoResponse)
async def activate_repo(repo_id: str, current: CurrentUser) -> RepoResponse:
    user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(Repository)
            .where(Repository.id == uuid.UUID(repo_id))
            .options(selectinload(Repository.connection))
        )
        repo = result.scalar_one_or_none()
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found.")
        repo.is_active = True
        await session.flush()
        refreshed = await session.execute(
            select(Repository)
            .where(Repository.id == repo.id)
            .options(selectinload(Repository.connection))
        )
        repo = refreshed.scalar_one()
        last_analysis_at = await _get_last_analysis_at(session, tenant_id, repo.id)
    return _repo_to_response(repo, last_analysis_at)


@router.post("/{repo_id}/deactivate", response_model=RepoResponse)
async def deactivate_repo(repo_id: str, current: CurrentUser) -> RepoResponse:
    user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(Repository)
            .where(Repository.id == uuid.UUID(repo_id))
            .options(selectinload(Repository.connection))
        )
        repo = result.scalar_one_or_none()
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found.")
        repo.is_active = False
        await session.flush()
        refreshed = await session.execute(
            select(Repository)
            .where(Repository.id == repo.id)
            .options(selectinload(Repository.connection))
        )
        repo = refreshed.scalar_one()
        last_analysis_at = await _get_last_analysis_at(session, tenant_id, repo.id)
    return _repo_to_response(repo, last_analysis_at)


class UpdateRepoContextRequest(BaseModel):
    repo_type: str | None = None
    app_subtype: str | None = None
    iac_provider: str | None = None
    language: list[str] | None = None
    observability_backend: str | None = None
    instrumentation: str | None = None
    obs_metadata: dict | None = None
    context_summary: str | None = None


@router.patch("/{repo_id}/context", response_model=RepoResponse)
async def update_repo_context(repo_id: str, body: UpdateRepoContextRequest, current: CurrentUser) -> RepoResponse:
    user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(Repository)
            .where(
                Repository.id == uuid.UUID(repo_id),
                Repository.tenant_id == uuid.UUID(tenant_id),
            )
            .options(selectinload(Repository.connection))
        )
        repo = result.scalar_one_or_none()
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found.")
        if body.repo_type is not None:
            repo.repo_type = body.repo_type
        if body.app_subtype is not None:
            repo.app_subtype = body.app_subtype
        if body.iac_provider is not None:
            repo.iac_provider = body.iac_provider
        if body.language is not None:
            repo.language = body.language
        if body.observability_backend is not None:
            repo.observability_backend = body.observability_backend
        if body.instrumentation is not None:
            repo.instrumentation = body.instrumentation
        if body.obs_metadata is not None:
            repo.obs_metadata = body.obs_metadata
        if body.context_summary is not None:
            repo.context_summary = body.context_summary
        await session.flush()
        refreshed = await session.execute(
            select(Repository)
            .where(Repository.id == repo.id)
            .options(selectinload(Repository.connection))
        )
        repo = refreshed.scalar_one()
        last_analysis_at = await _get_last_analysis_at(session, tenant_id, repo.id)
    return _repo_to_response(repo, last_analysis_at)


@router.post("/{repo_id}/scan-context", status_code=202)
async def scan_repo_context(repo_id: str, current: CurrentUser) -> dict:
    from apps.worker.tasks import scan_repo_context as _task
    _task.delay(repo_id)
    return {"status": "enqueued", "repo_id": repo_id}


@router.get("/{repo_id}/refs")
async def list_repo_refs(repo_id: str, current: CurrentUser) -> dict:
    """List branches and tags for a repository from its SCM provider."""
    user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(Repository)
            .where(Repository.id == uuid.UUID(repo_id))
            .options(selectinload(Repository.connection))
        )
        repo = result.scalar_one_or_none()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")

    connection = repo.connection
    if not connection:
        return {"branches": [repo.default_branch], "tags": []}

    with tracer.start_as_current_span("list_repo_refs") as span:
        try:
            from apps.api.core.security import decrypt_scm_token
            from apps.api.scm.github import GitHubAdapter
            from apps.api.scm import gitlab as gitlab_scm
            from apps.api.scm import bitbucket as bitbucket_scm

            if connection.scm_type == "github" and connection.installation_id:
                adapter = GitHubAdapter()
                return await adapter.list_refs(connection.installation_id, repo.full_name)
            if connection.scm_type == "gitlab":
                token = decrypt_scm_token(connection.encrypted_token)
                if token:
                    return await gitlab_scm.list_refs(token, repo.full_name)
            if connection.scm_type == "bitbucket":
                token = decrypt_scm_token(connection.encrypted_token)
                if token:
                    return await bitbucket_scm.list_refs(token, repo.full_name)
        except Exception as e:
            span.record_exception(e)
            span.set_status(StatusCode.ERROR, str(e))
            log.error("list_refs_failed", repo=repo.full_name, error=str(e), exc_info=True)
    return {"branches": [repo.default_branch], "tags": []}


@router.get("/{repo_id}/contents")
async def list_repo_contents(
    repo_id: str,
    current: CurrentUser,
    ref: str = Query(..., description="Branch or tag name"),
    path: str = Query("", description="Directory path relative to repo root"),
) -> list[dict]:
    """List files and subdirectories at a path (for browse/select scope before analysis)."""
    user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(Repository)
            .where(Repository.id == uuid.UUID(repo_id))
            .options(selectinload(Repository.connection))
        )
        repo = result.scalar_one_or_none()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found.")

    connection = repo.connection
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SCM connection required to browse repository contents.",
        )

    try:
        from apps.api.core.security import decrypt_scm_token
        from apps.api.scm.github import GitHubAdapter
        from apps.api.scm import gitlab as gitlab_scm
        from apps.api.scm import bitbucket as bitbucket_scm

        if connection.scm_type == "github" and connection.installation_id:
            adapter = GitHubAdapter()
            return await adapter.get_contents(
                connection.installation_id,
                repo.full_name,
                path=path,
                ref=ref,
            )
        if connection.scm_type == "gitlab":
            token = decrypt_scm_token(connection.encrypted_token)
            if not token:
                raise HTTPException(status_code=503, detail="GitLab token missing.")
            return await gitlab_scm.get_tree(token, repo.full_name, path=path, ref=ref)
        if connection.scm_type == "bitbucket":
            token = decrypt_scm_token(connection.encrypted_token)
            if not token:
                raise HTTPException(status_code=503, detail="Bitbucket token missing.")
            return await bitbucket_scm.get_src_directory(token, repo.full_name, path=path, ref=ref)
        raise HTTPException(status_code=503, detail="Unsupported SCM for browsing.")
    except HTTPException:
        raise
    except Exception as e:
        log.warning("list_contents_failed", repo=repo.full_name, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not load repository contents: {e!s}",
        ) from e


def _repo_to_response(repo: Repository, last_analysis_at=None) -> RepoResponse:
    scm_type = "github"
    try:
        if repo.connection is not None and repo.connection.scm_type:
            scm_type = repo.connection.scm_type
    except Exception:
        pass
    last_iso = None
    try:
        if last_analysis_at:
            last_iso = last_analysis_at.isoformat()
    except Exception:
        pass
    return RepoResponse(
        id=str(repo.id),
        full_name=repo.full_name,
        web_url=repo_web_url(
            scm_type=scm_type,
            full_name=repo.full_name,
            clone_url=getattr(repo, "clone_url", None),
        ),
        default_branch=repo.default_branch,
        is_active=repo.is_active,
        schedule_enabled=repo.schedule_enabled,
        schedule_cron=repo.schedule_cron,
        created_at=repo.created_at.isoformat(),
        scm_type=scm_type,
        repo_type=getattr(repo, "repo_type", None),
        app_subtype=getattr(repo, "app_subtype", None),
        iac_provider=getattr(repo, "iac_provider", None),
        language=getattr(repo, "language", None),
        observability_backend=getattr(repo, "observability_backend", None),
        instrumentation=getattr(repo, "instrumentation", None),
        obs_metadata=getattr(repo, "obs_metadata", None),
        context_summary=getattr(repo, "context_summary", None),
        last_analysis_at=last_iso,
    )


async def _get_last_analysis_at(session, tenant_id: str, repo_id) -> object | None:
    result = await session.execute(
        select(func.max(AnalysisJob.completed_at)).where(
            AnalysisJob.tenant_id == uuid.UUID(tenant_id),
            AnalysisJob.repo_id == repo_id,
            AnalysisJob.status == "completed",
        )
    )
    return result.scalar_one_or_none()
