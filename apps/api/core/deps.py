"""FastAPI dependency injection for authentication and authorization."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_no_rls
from apps.api.core.security import decode_access_token, hash_api_key
from apps.api.models.auth import ApiKey, TenantMembership, User

log = structlog.get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

# (user, active_tenant_id, membership_role: admin|operator|viewer)
AuthTriple = tuple[User, str, str]


async def _membership_role(session: AsyncSession, user_id: UUID, tenant_id: UUID) -> str:
    result = await session.execute(
        select(TenantMembership.role).where(
            TenantMembership.user_id == user_id,
            TenantMembership.tenant_id == tenant_id,
        )
    )
    role = result.scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this workspace.",
        )
    return str(role)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_db_no_rls),
) -> AuthTriple:
    """
    Returns (user, tenant_id, membership_role) from either:
    - Bearer JWT token (browser session)
    - X-Api-Key header (programmatic access)
    """
    if x_api_key:
        return await _auth_by_api_key(x_api_key, session)

    if credentials:
        return await _auth_by_jwt(credentials.credentials, session)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide Bearer token or X-Api-Key header.",
    )


async def _auth_by_api_key(api_key: str, session: AsyncSession) -> AuthTriple:
    key_hash = hash_api_key(api_key)
    result = await session.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
    )
    db_key = result.scalar_one_or_none()
    if not db_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")

    user_result = await session.execute(
        select(User).where(User.id == db_key.user_id)
    )
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive.")

    role = await _membership_role(session, user.id, db_key.tenant_id)
    structlog.contextvars.bind_contextvars(tenant_id=str(db_key.tenant_id))
    return user, str(db_key.tenant_id), role


async def _auth_by_jwt(token: str, session: AsyncSession) -> AuthTriple:
    try:
        payload = decode_access_token(token)
        user_id: str = payload.get("sub")
        tenant_id: str = payload.get("tenant_id")
        if not user_id or not tenant_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")

    result = await session.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive.")

    role = await _membership_role(session, user.id, UUID(tenant_id))
    structlog.contextvars.bind_contextvars(tenant_id=tenant_id)
    return user, tenant_id, role


async def require_tenant_admin(current: AuthTriple = Depends(get_current_user)) -> AuthTriple:
    _user, _tid, role = current
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required for this action.",
        )
    return current


CurrentUser = Annotated[AuthTriple, Depends(get_current_user)]
TenantAdmin = Annotated[AuthTriple, Depends(require_tenant_admin)]
