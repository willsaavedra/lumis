"""Tag catalog (tenant-scoped)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.core.database import get_session_with_tenant
from apps.api.core.deps import CurrentUser
from apps.api.models.teams import Tag

router = APIRouter()


class TagListItem(BaseModel):
    id: str
    key: str
    value: str


@router.get("", response_model=list[TagListItem])
async def list_tags(
    current: CurrentUser,
    key: str | None = Query(None, description="Filter by tag key"),
) -> list[TagListItem]:
    _user, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    async with get_session_with_tenant(tenant_id) as session:
        q = select(Tag).where(Tag.tenant_id == tid)
        if key and key.strip():
            q = q.where(Tag.key == key.strip())
        q = q.order_by(Tag.key, Tag.value)
        rows = (await session.execute(q)).scalars().all()
    return [TagListItem(id=str(t.id), key=t.key, value=t.value) for t in rows]
