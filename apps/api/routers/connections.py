"""SCM connection OAuth/App flows."""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from apps.api.core.config import settings
from apps.api.core.deps import CurrentUser
from apps.api.core.security import create_state_token, decode_state_token

log = structlog.get_logger(__name__)
router = APIRouter()


@router.get("")
async def list_connections(current: CurrentUser) -> list[dict]:
    """Return all active SCM connections for the tenant."""
    user, tenant_id, _ = current
    from apps.api.core.database import get_session_with_tenant
    from apps.api.models.scm import ScmConnection

    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(ScmConnection).where(ScmConnection.tenant_id == uuid.UUID(tenant_id))
        )
        connections = result.scalars().all()

    return [
        {
            "id": str(c.id),
            "scm_type": c.scm_type,
            "installation_id": c.installation_id,
            "org_login": c.org_login,
            "org_avatar_url": c.org_avatar_url,
            "created_at": c.created_at.isoformat(),
        }
        for c in connections
    ]


@router.get("/github")
async def github_connect(
    request: Request,
    token: str | None = None,
) -> RedirectResponse:
    """Redirect user to GitHub App installation page.

    Accepts auth via Bearer header OR ?token= query param (needed for browser redirects).
    """
    from apps.api.core.database import get_db_no_rls
    from apps.api.core.deps import _auth_by_jwt, _auth_by_api_key
    from apps.api.core.security import decode_access_token

    # Resolve auth: query param token, then Authorization header, then X-Api-Key
    bearer = request.headers.get("authorization", "")
    api_key_header = request.headers.get("x-api-key")

    raw_token = token or (bearer.removeprefix("Bearer ") if bearer.startswith("Bearer ") else None)

    current = None
    async for db in get_db_no_rls():
        if raw_token:
            current = await _auth_by_jwt(raw_token, db)
        elif api_key_header:
            current = await _auth_by_api_key(api_key_header, db)
        else:
            raise HTTPException(status_code=401, detail="Authentication required.")
        break

    user, tenant_id, _ = current
    if not settings.github_app_slug:
        raise HTTPException(status_code=500, detail="GitHub App not configured.")

    state = create_state_token(tenant_id=tenant_id, user_id=str(user.id))

    from apps.api.core.redis_client import get_redis
    redis = get_redis()
    await redis.setex(f"oauth_state:{state[:16]}", 600, state)

    install_url = (
        f"https://github.com/apps/{settings.github_app_slug}/installations/new"
        f"?state={state}"
    )
    return RedirectResponse(url=install_url)


@router.get("/github/callback")
async def github_callback(
    request: Request,
    installation_id: str | None = None,
    setup_action: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    """Handle GitHub App installation callback."""
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter.")

    try:
        state_data = decode_state_token(state)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired state token.")

    tenant_id = state_data["tenant_id"]

    if not installation_id:
        return RedirectResponse(url="/settings/connections?error=cancelled")

    from apps.api.core.config import settings as app_settings
    frontend = app_settings.frontend_url

    try:
        from apps.api.core.database import get_session_with_tenant
        from apps.api.models.scm import ScmConnection

        async with get_session_with_tenant(tenant_id) as session:
            # Upsert: avoid duplicate connections for the same installation
            existing = await session.execute(
                select(ScmConnection).where(
                    ScmConnection.tenant_id == uuid.UUID(tenant_id),
                    ScmConnection.scm_type == "github",
                )
            )
            connection = existing.scalar_one_or_none()
            if connection:
                connection.installation_id = str(installation_id)
            else:
                connection = ScmConnection(
                    tenant_id=uuid.UUID(tenant_id),
                    scm_type="github",
                    installation_id=str(installation_id),
                    org_login=None,
                )
                session.add(connection)

        log.info("github_app_installed", tenant_id=tenant_id, installation_id=installation_id)
        return RedirectResponse(url=f"{frontend}/settings?connected=github")

    except Exception as e:
        import traceback
        log.error("github_callback_failed", error=str(e), traceback=traceback.format_exc(), tenant_id=tenant_id)
        return RedirectResponse(url=f"{frontend}/settings?error=failed")


async def _resolve_browser_auth(request: Request, token: str | None):
    """Same as GitHub connect: JWT from ?token=, Bearer, or API key."""
    from apps.api.core.database import get_db_no_rls
    from apps.api.core.deps import _auth_by_jwt, _auth_by_api_key

    bearer = request.headers.get("authorization", "")
    api_key_header = request.headers.get("x-api-key")
    raw_token = token or (bearer.removeprefix("Bearer ") if bearer.startswith("Bearer ") else None)
    async for db in get_db_no_rls():
        if raw_token:
            return await _auth_by_jwt(raw_token, db)
        if api_key_header:
            return await _auth_by_api_key(api_key_header, db)
        raise HTTPException(status_code=401, detail="Authentication required.")
    raise HTTPException(status_code=401, detail="Authentication required.")


@router.get("/gitlab")
async def gitlab_connect(request: Request, token: str | None = None) -> RedirectResponse:
    """Redirect user to GitLab OAuth (browser: pass ?token= JWT)."""
    from urllib.parse import urlencode

    if not settings.gitlab_app_id or not settings.gitlab_app_secret:
        raise HTTPException(status_code=500, detail="GitLab OAuth not configured.")

    user, tenant_id, _ = await _resolve_browser_auth(request, token)
    state = create_state_token(tenant_id=tenant_id, user_id=str(user.id))
    redirect_uri = f"{settings.api_base_url.rstrip('/')}/connect/gitlab/callback"
    base = settings.gitlab_base_url.rstrip("/")
    oauth_url = f"{base}/oauth/authorize?" + urlencode(
        {
            "client_id": settings.gitlab_app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "read_api read_repository read_user",
            "state": state,
        }
    )
    return RedirectResponse(url=oauth_url)


@router.get("/gitlab/callback")
async def gitlab_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    """Exchange GitLab OAuth code and persist encrypted token."""
    frontend = settings.frontend_url.rstrip("/")
    if not state:
        return RedirectResponse(url=f"{frontend}/settings?error=gitlab_state")
    try:
        state_data = decode_state_token(state)
    except ValueError:
        return RedirectResponse(url=f"{frontend}/settings?error=gitlab_state")

    tenant_id = state_data["tenant_id"]
    if not code:
        return RedirectResponse(url=f"{frontend}/settings?error=gitlab_cancelled")

    redirect_uri = f"{settings.api_base_url.rstrip('/')}/connect/gitlab/callback"
    try:
        from apps.api.scm.gitlab import exchange_oauth_code, fetch_current_user
        from apps.api.core.security import encrypt_scm_token
        from apps.api.core.database import get_session_with_tenant
        from apps.api.models.scm import ScmConnection

        tokens = await exchange_oauth_code(code, redirect_uri)
        access = tokens.get("access_token")
        if not access:
            raise ValueError("no access_token in GitLab response")
        user_info = await fetch_current_user(access)
        uid = str(user_info.get("id", ""))
        login = user_info.get("username") or user_info.get("name")

        async with get_session_with_tenant(tenant_id) as session:
            existing = await session.execute(
                select(ScmConnection).where(
                    ScmConnection.tenant_id == uuid.UUID(tenant_id),
                    ScmConnection.scm_type == "gitlab",
                )
            )
            conn = existing.scalar_one_or_none()
            if conn:
                conn.installation_id = uid
                conn.org_login = login
                conn.encrypted_token = encrypt_scm_token(access)
            else:
                session.add(
                    ScmConnection(
                        tenant_id=uuid.UUID(tenant_id),
                        scm_type="gitlab",
                        installation_id=uid,
                        org_login=login,
                        encrypted_token=encrypt_scm_token(access),
                    )
                )
        log.info("gitlab_oauth_connected", tenant_id=tenant_id, user_id=uid)
        return RedirectResponse(url=f"{frontend}/settings?connected=gitlab")
    except Exception as e:
        log.error("gitlab_callback_failed", error=str(e), tenant_id=tenant_id)
        return RedirectResponse(url=f"{frontend}/settings?error=gitlab_failed")


@router.get("/bitbucket")
async def bitbucket_connect(request: Request, token: str | None = None) -> RedirectResponse:
    """Redirect to Bitbucket Cloud OAuth."""
    from urllib.parse import urlencode

    if not settings.bitbucket_client_id or not settings.bitbucket_client_secret:
        raise HTTPException(status_code=500, detail="Bitbucket OAuth not configured.")

    user, tenant_id, _ = await _resolve_browser_auth(request, token)
    state = create_state_token(tenant_id=tenant_id, user_id=str(user.id))
    redirect_uri = f"{settings.api_base_url.rstrip('/')}/connect/bitbucket/callback"
    oauth_url = "https://bitbucket.org/site/oauth2/authorize?" + urlencode(
        {
            "client_id": settings.bitbucket_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            "scope": "repository",
        }
    )
    return RedirectResponse(url=oauth_url)


@router.get("/bitbucket/callback")
async def bitbucket_callback(
    code: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    frontend = settings.frontend_url.rstrip("/")
    if not state:
        return RedirectResponse(url=f"{frontend}/settings?error=bitbucket_state")
    try:
        state_data = decode_state_token(state)
    except ValueError:
        return RedirectResponse(url=f"{frontend}/settings?error=bitbucket_state")

    tenant_id = state_data["tenant_id"]
    if not code:
        return RedirectResponse(url=f"{frontend}/settings?error=bitbucket_cancelled")

    redirect_uri = f"{settings.api_base_url.rstrip('/')}/connect/bitbucket/callback"
    try:
        from apps.api.scm import bitbucket as bb
        from apps.api.core.security import encrypt_scm_token
        from apps.api.core.database import get_session_with_tenant
        from apps.api.models.scm import ScmConnection

        tokens = await bb.exchange_oauth_code(code, redirect_uri)
        access = tokens.get("access_token")
        if not access:
            raise ValueError("no access_token in Bitbucket response")
        user_info = await bb.fetch_current_user(access)
        uid = str(user_info.get("uuid") or user_info.get("username") or "")
        login = user_info.get("username") or user_info.get("display_name") or uid

        async with get_session_with_tenant(tenant_id) as session:
            existing = await session.execute(
                select(ScmConnection).where(
                    ScmConnection.tenant_id == uuid.UUID(tenant_id),
                    ScmConnection.scm_type == "bitbucket",
                )
            )
            conn = existing.scalar_one_or_none()
            if conn:
                conn.installation_id = str(uid)
                conn.org_login = login
                conn.encrypted_token = encrypt_scm_token(access)
            else:
                session.add(
                    ScmConnection(
                        tenant_id=uuid.UUID(tenant_id),
                        scm_type="bitbucket",
                        installation_id=str(uid),
                        org_login=login,
                        encrypted_token=encrypt_scm_token(access),
                    )
                )
        log.info("bitbucket_oauth_connected", tenant_id=tenant_id)
        return RedirectResponse(url=f"{frontend}/settings?connected=bitbucket")
    except Exception as e:
        log.error("bitbucket_callback_failed", error=str(e), tenant_id=tenant_id)
        return RedirectResponse(url=f"{frontend}/settings?error=bitbucket_failed")
