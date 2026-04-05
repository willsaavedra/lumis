"""Team management endpoints."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.config import settings
from apps.api.core.database import get_session_with_tenant
from apps.api.core.deps import CurrentUser, TenantAdmin, get_db_no_rls
from apps.api.models.auth import TenantInvite, TenantMembership, User

log = structlog.get_logger(__name__)
router = APIRouter()

INVITE_EXPIRE_DAYS = 14


def _invite_token_hash(raw: str) -> str:
    import hashlib

    return hashlib.sha256(raw.encode()).hexdigest()


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "operator"

    @field_validator("role")
    @classmethod
    def role_ok(cls, v: str) -> str:
        if v not in ("admin", "operator", "viewer"):
            raise ValueError("role must be admin, operator, or viewer")
        return v


class InviteResponse(BaseModel):
    status: str
    email: str
    invite_url: str
    expires_at: str


class UpdateMemberRoleRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def role_ok(cls, v: str) -> str:
        if v not in ("admin", "operator", "viewer"):
            raise ValueError("role must be admin, operator, or viewer")
        return v


@router.get("/members")
async def list_members(current: CurrentUser) -> list[dict]:
    _user, tenant_id, _ = current
    async with get_session_with_tenant(tenant_id) as session:
        tid = uuid.UUID(tenant_id)
        q = (
            select(User, TenantMembership)
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .where(TenantMembership.tenant_id == tid)
            .where(User.is_active == True)
        )
        rows = (await session.execute(q)).all()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "role": str(m.role),
            "created_at": u.created_at.isoformat(),
        }
        for u, m in rows
    ]


@router.post("/invite", status_code=201, response_model=InviteResponse)
async def invite_member(
    body: InviteRequest,
    current: TenantAdmin,
    session: AsyncSession = Depends(get_db_no_rls),
) -> InviteResponse:
    admin_user, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    raw_token = secrets.token_urlsafe(32)
    token_hash = _invite_token_hash(raw_token)
    email_norm = body.email.strip().lower()
    expires = datetime.now(timezone.utc) + timedelta(days=INVITE_EXPIRE_DAYS)

    inv = TenantInvite(
        tenant_id=tid,
        email=email_norm,
        role=body.role,
        token_hash=token_hash,
        invited_by_user_id=admin_user.id,
        expires_at=expires,
    )
    session.add(inv)
    await session.flush()

    base = settings.frontend_url.rstrip("/")
    invite_url = f"{base}/invite?token={raw_token}"
    log.info("team_invite_created", tenant_id=tenant_id, email=email_norm, role=body.role)
    return InviteResponse(
        status="invited",
        email=email_norm,
        invite_url=invite_url,
        expires_at=expires.isoformat(),
    )


@router.delete("/members/{user_id}", status_code=204, response_model=None)
async def remove_member(
    user_id: str,
    current: TenantAdmin,
    session: AsyncSession = Depends(get_db_no_rls),
) -> None:
    admin_user, tenant_id, _ = current
    if str(admin_user.id) == user_id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself.")
    tid = uuid.UUID(tenant_id)
    target_uid = uuid.UUID(user_id)

    r = await session.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tid,
            TenantMembership.user_id == target_uid,
        )
    )
    if not r.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Member not found in this workspace.")

    await session.execute(
        delete(TenantMembership).where(
            TenantMembership.tenant_id == tid,
            TenantMembership.user_id == target_uid,
        )
    )


@router.patch("/members/{user_id}/role")
async def update_member_role(
    user_id: str,
    body: UpdateMemberRoleRequest,
    current: TenantAdmin,
    session: AsyncSession = Depends(get_db_no_rls),
) -> dict:
    """Change a member's role in the current workspace."""
    admin_user, tenant_id, _ = current
    if str(admin_user.id) == user_id:
        raise HTTPException(status_code=400, detail="Cannot change your own role here.")
    tid = uuid.UUID(tenant_id)
    target_uid = uuid.UUID(user_id)

    r = await session.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tid,
            TenantMembership.user_id == target_uid,
        )
    )
    m = r.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Member not found.")
    m.role = body.role
    return {"user_id": user_id, "role": body.role}
