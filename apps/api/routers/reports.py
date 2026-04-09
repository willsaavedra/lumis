"""Aggregated reporting (by tag / team)."""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from apps.api.core.database import get_session_with_tenant
from apps.api.core.deps import CurrentUser
from apps.api.models.analysis import AnalysisJob
from apps.api.models.scm import Repository
from apps.api.models.teams import RepositoryTag, Tag, Team
from apps.api.services.tag_access import effective_tag_ids_for_user

log = structlog.get_logger(__name__)
router = APIRouter()


class TagSummaryRow(BaseModel):
    tag_id: str
    key: str
    value: str
    team_id: str | None = None
    team_slug: str | None = None
    repository_count: int
    completed_analysis_count: int


class SummaryByTagResponse(BaseModel):
    items: list[TagSummaryRow]


def _visible_repo_ids_subquery(eff: list[uuid.UUID] | None):
    if eff is None:
        return None
    return select(RepositoryTag.repository_id).where(RepositoryTag.tag_id.in_(eff)).distinct()


@router.get("/summary-by-tag", response_model=SummaryByTagResponse)
async def summary_by_tag(current: CurrentUser) -> SummaryByTagResponse:
    user, tenant_id, membership_role = current
    tid = uuid.UUID(tenant_id)

    async with get_session_with_tenant(tenant_id) as session:
        eff = await effective_tag_ids_for_user(
            session,
            tenant_id=tenant_id,
            user_id=user.id,
            membership_role=membership_role,
        )
        vis = _visible_repo_ids_subquery(eff)

        tag_q = select(Tag).where(Tag.tenant_id == tid)
        if eff is not None:
            tag_q = tag_q.where(Tag.id.in_(eff))
        tags = (await session.execute(tag_q.order_by(Tag.key, Tag.value))).scalars().all()

        team_rows = (
            await session.execute(
                select(Team).where(Team.tenant_id == tid).options(selectinload(Team.default_tag_row))
            )
        ).scalars().all()
        tag_to_team: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
        for tm in team_rows:
            tag_to_team[tm.default_tag_id] = (tm.id, tm.slug)

        items: list[TagSummaryRow] = []
        for tag in tags:
            rc = select(func.count(func.distinct(RepositoryTag.repository_id))).where(
                RepositoryTag.tag_id == tag.id
            )
            if vis is not None:
                rc = rc.where(RepositoryTag.repository_id.in_(vis))
            n_repos = int((await session.execute(rc)).scalar_one() or 0)

            aj = (
                select(func.count(func.distinct(AnalysisJob.id)))
                .select_from(AnalysisJob)
                .join(Repository, AnalysisJob.repo_id == Repository.id)
                .where(
                    AnalysisJob.tenant_id == tid,
                    AnalysisJob.status == "completed",
                )
            )
            if vis is not None:
                aj = aj.where(AnalysisJob.repo_id.in_(vis))
            aj = aj.where(
                AnalysisJob.repo_id.in_(
                    select(RepositoryTag.repository_id).where(RepositoryTag.tag_id == tag.id)
                )
            )
            n_an = int((await session.execute(aj)).scalar_one() or 0)

            tm_info = tag_to_team.get(tag.id)
            items.append(
                TagSummaryRow(
                    tag_id=str(tag.id),
                    key=tag.key,
                    value=tag.value,
                    team_id=str(tm_info[0]) if tm_info else None,
                    team_slug=tm_info[1] if tm_info else None,
                    repository_count=n_repos,
                    completed_analysis_count=n_an,
                )
            )

    return SummaryByTagResponse(items=items)
