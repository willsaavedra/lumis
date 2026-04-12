"""CRUD for tag definitions + repo tags management."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_session_with_tenant
from apps.api.core.deps import CurrentUser, TenantAdmin
from apps.api.models.tag_system import AnalysisTag, RepoTag, TagDefinition
from apps.api.services.tag_service import TagInput, seed_default_tag_definitions, validate_and_warn

log = structlog.get_logger(__name__)
router = APIRouter()

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,48}[a-z0-9]$")


# ── Schemas ─────────────────────────────────────────────────────────────

class TagDefinitionOut(BaseModel):
    id: str
    key: str
    label: str
    description: str | None = None
    required: bool
    allowed_values: list[str] | None = None
    color_class: str | None = None
    sort_order: int
    repos_using_count: int = 0
    created_at: str
    updated_at: str


class CreateTagDefinitionRequest(BaseModel):
    key: str = Field(..., min_length=2, max_length=50)
    label: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    required: bool = False
    allowed_values: list[str] | None = None
    color_class: str | None = None
    sort_order: int = 0


class UpdateTagDefinitionRequest(BaseModel):
    label: str | None = None
    description: str | None = None
    required: bool | None = None
    allowed_values: list[str] | None = None
    color_class: str | None = None
    sort_order: int | None = None


class RepoTagOut(BaseModel):
    key: str
    value: str
    source: str
    definition: TagDefinitionOut | None = None


class SetRepoTagsRequest(BaseModel):
    tags: list[dict[str, str]] = Field(
        default_factory=list,
        description="List of {key, value} pairs",
    )


class PatchRepoTagsRequest(BaseModel):
    tags: list[dict[str, str]] = Field(
        default_factory=list,
        description="Partial upsert list of {key, value}",
    )


class TagValueItem(BaseModel):
    value: str
    count: int


# ── Tag Definitions CRUD ────────────────────────────────────────────────

@router.get("", response_model=list[TagDefinitionOut])
async def list_definitions(current: CurrentUser) -> list[TagDefinitionOut]:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    async with get_session_with_tenant(tenant_id) as session:
        existing_n = (
            await session.execute(select(func.count()).select_from(TagDefinition).where(TagDefinition.tenant_id == tid))
        ).scalar_one()
        if existing_n == 0:
            await seed_default_tag_definitions(session, tid)

        repo_count_sub = (
            select(func.count(RepoTag.id))
            .where(RepoTag.tenant_id == tid, RepoTag.key == TagDefinition.key)
            .correlate(TagDefinition)
            .scalar_subquery()
        )
        q = (
            select(TagDefinition, repo_count_sub.label("cnt"))
            .where(TagDefinition.tenant_id == tid)
            .order_by(TagDefinition.sort_order, TagDefinition.key)
        )
        rows = (await session.execute(q)).all()
    return [
        TagDefinitionOut(
            id=str(d.id), key=d.key, label=d.label,
            description=d.description, required=d.required,
            allowed_values=d.allowed_values, color_class=d.color_class,
            sort_order=d.sort_order, repos_using_count=cnt or 0,
            created_at=d.created_at.isoformat(), updated_at=d.updated_at.isoformat(),
        )
        for d, cnt in rows
    ]


@router.post("", response_model=TagDefinitionOut, status_code=status.HTTP_201_CREATED)
async def create_definition(body: CreateTagDefinitionRequest, current: TenantAdmin) -> TagDefinitionOut:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    key = body.key.strip().lower()
    if not _KEY_RE.match(key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Key must be lowercase alphanumeric with hyphens (2-50 chars).",
        )
    async with get_session_with_tenant(tenant_id) as session:
        exists = await session.execute(
            select(TagDefinition.id).where(TagDefinition.tenant_id == tid, TagDefinition.key == key)
        )
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Tag key '{key}' already exists.")
        defn = TagDefinition(
            tenant_id=tid, key=key, label=body.label,
            description=body.description, required=body.required,
            allowed_values=body.allowed_values, color_class=body.color_class,
            sort_order=body.sort_order,
        )
        session.add(defn)
        await session.flush()
        await session.refresh(defn)
    return TagDefinitionOut(
        id=str(defn.id), key=defn.key, label=defn.label,
        description=defn.description, required=defn.required,
        allowed_values=defn.allowed_values, color_class=defn.color_class,
        sort_order=defn.sort_order, repos_using_count=0,
        created_at=defn.created_at.isoformat(), updated_at=defn.updated_at.isoformat(),
    )


@router.patch("/{def_id}", response_model=TagDefinitionOut)
async def update_definition(def_id: str, body: UpdateTagDefinitionRequest, current: TenantAdmin) -> TagDefinitionOut:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(TagDefinition).where(TagDefinition.tenant_id == tid, TagDefinition.id == uuid.UUID(def_id))
        )
        defn = result.scalar_one_or_none()
        if not defn:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag definition not found.")
        if body.label is not None:
            defn.label = body.label
        if body.description is not None:
            defn.description = body.description
        if body.required is not None:
            defn.required = body.required
        if body.allowed_values is not None:
            defn.allowed_values = body.allowed_values
        if body.color_class is not None:
            defn.color_class = body.color_class
        if body.sort_order is not None:
            defn.sort_order = body.sort_order
        defn.updated_at = datetime.now(timezone.utc)
        await session.flush()
        await session.refresh(defn)
        cnt_r = await session.execute(
            select(func.count(RepoTag.id)).where(RepoTag.tenant_id == tid, RepoTag.key == defn.key)
        )
        cnt = cnt_r.scalar() or 0
    return TagDefinitionOut(
        id=str(defn.id), key=defn.key, label=defn.label,
        description=defn.description, required=defn.required,
        allowed_values=defn.allowed_values, color_class=defn.color_class,
        sort_order=defn.sort_order, repos_using_count=cnt,
        created_at=defn.created_at.isoformat(), updated_at=defn.updated_at.isoformat(),
    )


@router.delete("/{def_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_definition(def_id: str, current: TenantAdmin) -> None:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(TagDefinition).where(TagDefinition.tenant_id == tid, TagDefinition.id == uuid.UUID(def_id))
        )
        defn = result.scalar_one_or_none()
        if not defn:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag definition not found.")
        if defn.required:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete a required tag definition. Unmark 'required' first.",
            )
        await session.delete(defn)


# ── Repo Tags Endpoints (on repository router) ─────────────────────────

repo_tags_router = APIRouter()


@repo_tags_router.get("/{repo_id}/metadata-tags", response_model=list[RepoTagOut])
async def get_repo_tags(repo_id: str, current: CurrentUser) -> list[RepoTagOut]:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    rid = uuid.UUID(repo_id)
    async with get_session_with_tenant(tenant_id) as session:
        tags_r = await session.execute(
            select(RepoTag).where(RepoTag.tenant_id == tid, RepoTag.repo_id == rid).order_by(RepoTag.key)
        )
        tags = tags_r.scalars().all()
        defs_r = await session.execute(
            select(TagDefinition).where(TagDefinition.tenant_id == tid)
        )
        defs = {d.key: d for d in defs_r.scalars().all()}
    out: list[RepoTagOut] = []
    for t in tags:
        d = defs.get(t.key)
        defn_out = TagDefinitionOut(
            id=str(d.id), key=d.key, label=d.label, description=d.description,
            required=d.required, allowed_values=d.allowed_values,
            color_class=d.color_class, sort_order=d.sort_order,
            created_at=d.created_at.isoformat(), updated_at=d.updated_at.isoformat(),
        ) if d else None
        out.append(RepoTagOut(key=t.key, value=t.value, source=t.source, definition=defn_out))
    return out


@repo_tags_router.put("/{repo_id}/metadata-tags", response_model=list[RepoTagOut])
async def replace_repo_tags(repo_id: str, body: SetRepoTagsRequest, current: TenantAdmin) -> list[RepoTagOut]:
    """Full replace of user-managed tags. Auto-source tags are preserved unless explicitly overridden."""
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    rid = uuid.UUID(repo_id)
    inputs = [TagInput(key=t["key"], value=t["value"]) for t in body.tags if t.get("key") and t.get("value")]

    async with get_session_with_tenant(tenant_id) as session:
        auto_r = await session.execute(
            select(RepoTag).where(RepoTag.repo_id == rid, RepoTag.source == "auto")
        )
        auto_tags = {a.key: a for a in auto_r.scalars().all()}

        vr = await validate_and_warn(session, tenant_id, inputs, existing_keys=set(auto_tags.keys()))
        if not vr.valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[{"key": e.key, "message": e.message} for e in vr.errors],
            )

        await session.execute(
            delete(RepoTag).where(RepoTag.repo_id == rid, RepoTag.source != "auto")
        )

        provided_keys = set()
        for inp in inputs:
            provided_keys.add(inp.key)
            if inp.key in auto_tags:
                auto_tags[inp.key].value = inp.value
                auto_tags[inp.key].source = "user"
                auto_tags[inp.key].updated_at = datetime.now(timezone.utc)
            else:
                session.add(RepoTag(
                    tenant_id=tid, repo_id=rid, key=inp.key, value=inp.value, source="user",
                ))
        await session.flush()

    return await get_repo_tags(repo_id, current)


@repo_tags_router.patch("/{repo_id}/metadata-tags", response_model=list[RepoTagOut])
async def patch_repo_tags(repo_id: str, body: PatchRepoTagsRequest, current: TenantAdmin) -> list[RepoTagOut]:
    """Partial upsert — adds or updates the given keys, leaves others untouched."""
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    rid = uuid.UUID(repo_id)
    inputs = [TagInput(key=t["key"], value=t["value"]) for t in body.tags if t.get("key") and t.get("value")]
    if not inputs:
        return await get_repo_tags(repo_id, current)

    async with get_session_with_tenant(tenant_id) as session:
        # Load existing tags first so validation considers the full post-patch state.
        existing_r = await session.execute(
            select(RepoTag).where(RepoTag.repo_id == rid)
        )
        by_key = {rt.key: rt for rt in existing_r.scalars().all()}
        existing_keys = set(by_key.keys())

        vr = await validate_and_warn(session, tenant_id, inputs, existing_keys=existing_keys)
        if not vr.valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[{"key": e.key, "message": e.message} for e in vr.errors],
            )

        for inp in inputs:
            if inp.key in by_key:
                by_key[inp.key].value = inp.value
                by_key[inp.key].source = "user"
                by_key[inp.key].updated_at = datetime.now(timezone.utc)
            else:
                session.add(RepoTag(
                    tenant_id=tid, repo_id=rid, key=inp.key, value=inp.value, source="user",
                ))
        await session.flush()

    return await get_repo_tags(repo_id, current)


@repo_tags_router.delete(
    "/{repo_id}/metadata-tags/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_repo_tag(repo_id: str, key: str, current: TenantAdmin) -> None:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    rid = uuid.UUID(repo_id)
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(RepoTag).where(RepoTag.repo_id == rid, RepoTag.key == key)
        )
        rt = result.scalar_one_or_none()
        if not rt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tag '{key}' not found on repo.")
        await session.delete(rt)


# ── Tag Values Autocomplete ─────────────────────────────────────────────

tag_values_router = APIRouter()


@tag_values_router.get("/values", response_model=list[TagValueItem])
async def tag_values_autocomplete(
    current: CurrentUser,
    key: str = Query(..., min_length=1),
    q: str = Query("", description="Prefix filter on value"),
) -> list[TagValueItem]:
    _, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    async with get_session_with_tenant(tenant_id) as session:
        stmt = (
            select(RepoTag.value, func.count(RepoTag.id).label("cnt"))
            .where(RepoTag.tenant_id == tid, RepoTag.key == key)
        )
        if q.strip():
            stmt = stmt.where(RepoTag.value.ilike(f"{q.strip()}%"))
        stmt = stmt.group_by(RepoTag.value).order_by(func.count(RepoTag.id).desc()).limit(50)
        rows = (await session.execute(stmt)).all()
    return [TagValueItem(value=v, count=c) for v, c in rows]
