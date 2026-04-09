"""Platform teams: CRUD, members, default tag per team."""
from __future__ import annotations

import re
import uuid

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from apps.api.core.database import get_session_with_tenant
from apps.api.core.deps import CurrentUser, TenantAdmin
from apps.api.models.auth import User
from apps.api.models.teams import Tag, Team, TeamMembership

log = structlog.get_logger(__name__)
router = APIRouter()

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

TAG_KEY_TEAM = "team"


class TagBrief(BaseModel):
    id: str
    key: str
    value: str


class TeamResponse(BaseModel):
    id: str
    name: str
    slug: str
    default_tag: TagBrief
    created_at: str


class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    slug: str = Field(..., min_length=1, max_length=64)


class PatchTeamRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)


class AddTeamMembersRequest(BaseModel):
    user_ids: list[str] = Field(..., min_length=1)


class TeamMemberRow(BaseModel):
    user_id: str
    email: str


def _team_to_response(team: Team) -> TeamResponse:
    tag = team.default_tag_row
    return TeamResponse(
        id=str(team.id),
        name=team.name,
        slug=team.slug,
        default_tag=TagBrief(id=str(tag.id), key=tag.key, value=tag.value),
        created_at=team.created_at.isoformat(),
    )


@router.get("", response_model=list[TeamResponse])
async def list_teams(current: CurrentUser) -> list[TeamResponse]:
    _user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        r = await session.execute(
            select(Team)
            .where(Team.tenant_id == uuid.UUID(tenant_id))
            .options(selectinload(Team.default_tag_row))
            .order_by(Team.name)
        )
        teams = r.scalars().all()
    return [_team_to_response(t) for t in teams]


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(body: CreateTeamRequest, current: TenantAdmin) -> TeamResponse:
    _admin, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    slug = body.slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(
            status_code=400,
            detail="slug must be lowercase alphanumeric, start with a letter or digit, max 63 chars.",
        )
    async with get_session_with_tenant(tenant_id) as session:
        dup = await session.execute(select(Team.id).where(Team.tenant_id == tid, Team.slug == slug))
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="A team with this slug already exists.")
        tag = Tag(tenant_id=tid, key=TAG_KEY_TEAM, value=slug)
        session.add(tag)
        await session.flush()
        team = Team(tenant_id=tid, name=body.name.strip(), slug=slug, default_tag_id=tag.id)
        session.add(team)
        await session.flush()
        r2 = await session.execute(
            select(Team)
            .where(Team.id == team.id)
            .options(selectinload(Team.default_tag_row))
        )
        team = r2.scalar_one()
        out = _team_to_response(team)
    log.info("team_created", team_id=out.id, tenant_id=tenant_id, slug=slug)
    return out


@router.get("/{team_id}/members", response_model=list[TeamMemberRow])
async def list_team_members(team_id: str, current: TenantAdmin) -> list[TeamMemberRow]:
    """List users in a team (admin)."""
    _admin, tenant_id, _ = current
    try:
        t_uuid = uuid.UUID(team_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid team_id.") from e
    tid = uuid.UUID(tenant_id)
    async with get_session_with_tenant(tenant_id) as session:
        tr = await session.execute(select(Team.id).where(Team.id == t_uuid, Team.tenant_id == tid))
        if not tr.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Team not found.")
        r = await session.execute(
            select(User.id, User.email)
            .join(TeamMembership, TeamMembership.user_id == User.id)
            .where(
                TeamMembership.team_id == t_uuid,
                TeamMembership.tenant_id == tid,
                User.tenant_id == tid,
            )
            .order_by(User.email)
        )
        rows = r.all()
    return [TeamMemberRow(user_id=str(uid), email=email) for uid, email in rows]


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(team_id: str, current: CurrentUser) -> TeamResponse:
    _user, tenant_id, _ = current
    try:
        tid = uuid.UUID(team_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid team_id.") from e
    async with get_session_with_tenant(tenant_id) as session:
        r = await session.execute(
            select(Team)
            .where(Team.id == tid, Team.tenant_id == uuid.UUID(tenant_id))
            .options(selectinload(Team.default_tag_row))
        )
        team = r.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")
    return _team_to_response(team)


@router.patch("/{team_id}", response_model=TeamResponse)
async def patch_team(team_id: str, body: PatchTeamRequest, current: TenantAdmin) -> TeamResponse:
    _admin, tenant_id, _ = current
    try:
        tid = uuid.UUID(team_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid team_id.") from e
    async with get_session_with_tenant(tenant_id) as session:
        r = await session.execute(
            select(Team)
            .where(Team.id == tid, Team.tenant_id == uuid.UUID(tenant_id))
            .options(selectinload(Team.default_tag_row))
        )
        team = r.scalar_one_or_none()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")
        if body.name is not None:
            team.name = body.name.strip()
        await session.flush()
        out = _team_to_response(team)
    return out


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: str, current: TenantAdmin) -> None:
    _admin, tenant_id, _ = current
    try:
        tid = uuid.UUID(team_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid team_id.") from e
    async with get_session_with_tenant(tenant_id) as session:
        r = await session.execute(
            select(Team).where(Team.id == tid, Team.tenant_id == uuid.UUID(tenant_id))
        )
        team = r.scalar_one_or_none()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found.")
        await session.execute(delete(TeamMembership).where(TeamMembership.team_id == tid))
        await session.delete(team)
    log.info("team_deleted", team_id=team_id, tenant_id=tenant_id)


@router.post("/{team_id}/members", status_code=status.HTTP_204_NO_CONTENT)
async def add_team_members(team_id: str, body: AddTeamMembersRequest, current: TenantAdmin) -> None:
    _admin, tenant_id, _ = current
    try:
        t_uuid = uuid.UUID(team_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid team_id.") from e
    tid = uuid.UUID(tenant_id)
    async with get_session_with_tenant(tenant_id) as session:
        tr = await session.execute(select(Team).where(Team.id == t_uuid, Team.tenant_id == tid))
        if not tr.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Team not found.")
        for uid_str in body.user_ids:
            try:
                uid = uuid.UUID(uid_str)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid user id: {uid_str}") from e
            ex = await session.execute(
                select(TeamMembership.id).where(
                    TeamMembership.team_id == t_uuid,
                    TeamMembership.user_id == uid,
                )
            )
            if ex.scalar_one_or_none():
                continue
            session.add(TeamMembership(team_id=t_uuid, user_id=uid, tenant_id=tid))
        await session.flush()


@router.delete("/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_member(team_id: str, user_id: str, current: TenantAdmin) -> None:
    _admin, tenant_id, _ = current
    try:
        t_uuid = uuid.UUID(team_id)
        u_uuid = uuid.UUID(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid id.") from e
    async with get_session_with_tenant(tenant_id) as session:
        await session.execute(
            delete(TeamMembership).where(
                TeamMembership.team_id == t_uuid,
                TeamMembership.user_id == u_uuid,
                TeamMembership.tenant_id == uuid.UUID(tenant_id),
            )
        )
