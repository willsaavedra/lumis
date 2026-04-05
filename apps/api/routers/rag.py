"""RAG knowledge base management endpoints."""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.core.database import get_session_with_tenant
from apps.api.core.deps import CurrentUser
from apps.api.models.scm import Repository

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


class IngestStandardsRequest(BaseModel):
    repo_id: str
    yaml_content: str


class IngestStandardsResponse(BaseModel):
    status: str
    task_id: str | None = None
    message: str


@router.post("/ingest/standards", response_model=IngestStandardsResponse)
async def ingest_tenant_standards(
    body: IngestStandardsRequest,
    auth: CurrentUser,
) -> IngestStandardsResponse:
    """
    Manually trigger ingestion of a lumis.yaml file for a repository.
    This updates the tenant's knowledge index with the latest standards.
    """
    _, tenant_id, _ = auth

    from apps.agent.tasks.ingest_tenant_standards import ingest_tenant_standards as _task

    async with get_session_with_tenant(tenant_id) as session:
        repo = (await session.execute(
            select(Repository).where(
                Repository.id == uuid.UUID(body.repo_id),
                Repository.tenant_id == uuid.UUID(tenant_id),
            )
        )).scalar_one_or_none()

        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found.")
        repo_full_name = repo.full_name

    result = _task.delay(tenant_id, body.yaml_content, repo_full_name)
    log.info("standards_ingest_triggered", tenant_id=tenant_id, repo_id=body.repo_id)

    return IngestStandardsResponse(
        status="enqueued",
        task_id=result.id,
        message="Standards ingestion queued. Knowledge base will be updated shortly.",
    )
