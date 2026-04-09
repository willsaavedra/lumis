"""Apply repository_tags when activating a repository."""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.models.auth import User
from apps.api.models.teams import RepositoryTag, Tag, Team, TeamMembership


async def _validate_tag_ids_for_tenant(
    session: AsyncSession, tenant_id: uuid.UUID, tag_id_strs: list[str]
) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for s in tag_id_strs:
        try:
            tid = uuid.UUID(s.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid tag id: {s}") from e
        r = await session.execute(
            select(Tag.id).where(Tag.id == tid, Tag.tenant_id == tenant_id)
        )
        if r.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail=f"Unknown tag id for this workspace: {s}")
        out.append(tid)
    return out


async def _user_team_rows(session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> list[Team]:
    r = await session.execute(
        select(Team)
        .join(TeamMembership, TeamMembership.team_id == Team.id)
        .where(TeamMembership.tenant_id == tenant_id, TeamMembership.user_id == user_id)
        .options(selectinload(Team.default_tag_row))
    )
    return list(r.scalars().all())


async def _user_in_team(
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, team_id: uuid.UUID
) -> bool:
    r = await session.execute(
        select(TeamMembership.id).where(
            TeamMembership.tenant_id == tenant_id,
            TeamMembership.user_id == user_id,
            TeamMembership.team_id == team_id,
        )
    )
    return r.scalar_one_or_none() is not None


async def resolve_and_replace_repository_tags(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    repo_id: uuid.UUID,
    user: User,
    membership_role: str,
    team_id: str | None,
    tag_ids: list[str] | None,
    is_new_repo: bool,
) -> None:
    """
    Update repository_tags when activating or patching a repository.

    - If neither team_id nor tag_ids is sent and repo is not new: skip (keep existing tags).
    - If tag_ids is [] (explicit): start empty, then add team default if team_id set.
    - If only team_id: set to that team's default tag.
    - If only tag_ids (non-empty): set to those tags.
    - If new repo and nothing sent: single team -> add its tag; multiple teams -> 400.
    """
    explicit = team_id is not None or tag_ids is not None

    if not explicit and not is_new_repo:
        return

    resolved: set[uuid.UUID] = set()

    if tag_ids is not None:
        if len(tag_ids) > 0:
            resolved.update(await _validate_tag_ids_for_tenant(session, tenant_id, tag_ids))
        # else: empty list — start cleared; team_id may add below

    if team_id is not None:
        try:
            tmid = uuid.UUID(team_id.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail="Invalid team_id.") from e
        tr = await session.execute(
            select(Team).where(Team.id == tmid, Team.tenant_id == tenant_id)
        )
        team = tr.scalar_one_or_none()
        if not team:
            raise HTTPException(status_code=400, detail="Unknown team_id.")
        if membership_role != "admin":
            if not await _user_in_team(session, tenant_id, user.id, tmid):
                raise HTTPException(status_code=403, detail="You are not a member of this team.")
        resolved.add(team.default_tag_id)

    if not resolved and not explicit and is_new_repo:
        user_teams = await _user_team_rows(session, tenant_id, user.id)
        if len(user_teams) == 1:
            resolved.add(user_teams[0].default_tag_id)
        elif len(user_teams) > 1:
            raise HTTPException(
                status_code=400,
                detail="team_id is required when you belong to more than one team.",
            )

    await session.execute(delete(RepositoryTag).where(RepositoryTag.repository_id == repo_id))
    for tag_uuid in resolved:
        session.add(RepositoryTag(repository_id=repo_id, tag_id=tag_uuid))
    await session.flush()
