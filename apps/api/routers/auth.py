"""Authentication endpoints: signup, login, API key management."""
from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.config import settings
from apps.api.core.database import get_db_no_rls
from apps.api.core.deps import CurrentUser
from apps.api.core.redis_client import get_redis
from apps.api.core.security import (
    create_access_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from apps.api.models.auth import ApiKey, Organization, Tenant, TenantInvite, TenantMembership, User
from apps.api.services.tag_service import seed_default_tag_definitions

log = structlog.get_logger(__name__)
router = APIRouter()


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    company_name: str
    invite_token: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v

    @field_validator("company_name")
    @classmethod
    def company_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Company name cannot be empty.")
        return v.strip()


class SignupResponse(BaseModel):
    tenant_id: str
    user_id: str
    api_key: str  # Plaintext — shown ONCE, never again
    message: str = "Save your API key — it will never be shown again."


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    active_tenant_id: str | None = None


class TenantSummary(BaseModel):
    tenant_id: str
    name: str
    slug: str
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    user_id: str
    api_key_hint: str
    tenants: list[TenantSummary] = []
    must_select_tenant: bool = False
    membership_role: str = "member"


class SwitchTenantRequest(BaseModel):
    tenant_id: str


class SwitchTenantResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    membership_role: str


class MeResponse(BaseModel):
    email: str
    user_id: str
    active_tenant_id: str
    membership_role: str
    tenants: list[TenantSummary]
    needs_tenant_profile: bool
    needs_onboarding: bool = False
    email_verified: bool = True


class InvitePreviewResponse(BaseModel):
    tenant_name: str
    tenant_slug: str
    email: str
    role: str
    expired: bool
    accepted: bool


class ApiKeyResponse(BaseModel):
    id: str
    label: str
    key_hint: str
    scope: list[str]
    is_active: bool
    created_at: str


class CreateApiKeyRequest(BaseModel):
    label: str = "New Key"
    scope: list[str] = ["*"]


class CreateApiKeyResponse(BaseModel):
    id: str
    api_key: str  # Plaintext — shown ONCE
    label: str
    key_hint: str
    message: str = "Save your API key — it will never be shown again."


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{slug}-{uuid.uuid4().hex[:6]}"


def _invite_token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _tenant_summaries_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[TenantSummary]:
    q = (
        select(TenantMembership, Tenant)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(TenantMembership.user_id == user_id)
        .order_by(Tenant.name)
    )
    rows = (await session.execute(q)).all()
    return [
        TenantSummary(
            tenant_id=str(m.tenant_id),
            name=t.name,
            slug=t.slug,
            role=str(m.role),
        )
        for m, t in rows
    ]


def _google_redirect_uri() -> str:
    if settings.google_oauth_redirect_uri:
        return settings.google_oauth_redirect_uri.strip()
    return f"{settings.api_base_url.rstrip('/')}/auth/google/callback"


async def _exchange_google_code(code: str) -> dict:
    """Return Google OIDC userinfo (sub, email, email_verified, name, ...)."""
    redirect_uri = _google_redirect_uri()
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_res.status_code != 200:
            log.warning("google_token_exchange_failed", body=token_res.text[:200])
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google sign-in failed.")
        tokens = token_res.json()
        access = tokens.get("access_token")
        if not access:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Google response.")

        ui_res = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access}"},
        )
        if ui_res.status_code != 200:
            log.warning("google_userinfo_failed", body=ui_res.text[:200])
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not read Google profile.")
        return ui_res.json()


async def _find_or_create_google_user(session: AsyncSession, profile: dict) -> User:
    """
    Link or create user from Google profile.
    profile: sub, email, email_verified, name (optional)
    """
    sub = profile.get("sub")
    email_raw = profile.get("email")
    verified = profile.get("email_verified", False)
    name = (profile.get("name") or "").strip()

    if not sub or not email_raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google did not return email.")
    if not verified:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google email is not verified.")

    email_norm = email_raw.strip().lower()

    # 1) Existing Google account
    r1 = await session.execute(select(User).where(User.oauth_google_sub == sub))
    existing_g = r1.scalar_one_or_none()
    if existing_g:
        return existing_g

    # 2) Same email — link Google to existing password account
    r2 = await session.execute(select(User).where(func.lower(User.email) == email_norm))
    by_email = r2.scalar_one_or_none()
    if by_email:
        if by_email.oauth_google_sub and by_email.oauth_google_sub != sub:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already linked to another Google account.",
            )
        by_email.oauth_google_sub = sub
        await session.flush()
        return by_email

    # 3) New user — same provisioning as email/password signup (no password)
    company = name if name else email_norm.split("@")[0]
    tenant = Tenant(
        name=company,
        slug=_slugify(company),
        plan="free",
        credits_remaining=50,
        credits_monthly_limit=50,
        needs_profile_completion=False,
        needs_onboarding=True,
    )
    session.add(tenant)
    await session.flush()

    org = Organization(tenant_id=tenant.id, name=company)
    session.add(org)
    await session.flush()

    user = User(
        tenant_id=tenant.id,
        org_id=org.id,
        email=email_norm,
        password_hash=None,
        oauth_google_sub=sub,
        role="owner",
        email_verified=True,  # Google already validated the email
    )
    session.add(user)
    await session.flush()

    session.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="admin"))
    await session.flush()

    plaintext_key, key_hash, key_hint = generate_api_key()
    api_key = ApiKey(
        tenant_id=tenant.id,
        user_id=user.id,
        key_hash=key_hash,
        key_hint=key_hint,
        label="Default",
        scope=["*"],
    )
    session.add(api_key)
    await session.flush()

    await seed_default_tag_definitions(session, tenant.id)

    log.info("google_user_created", email=email_norm, user_id=str(user.id))

    # Send welcome email immediately (Google accounts are pre-verified)
    asyncio.ensure_future(_send_welcome_email_bg(email_norm))

    return user


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest,
    session: AsyncSession = Depends(get_db_no_rls),
) -> SignupResponse:
    """
    Atomic signup: creates tenant + organization + user + API key in one transaction.
    Returns the API key plaintext exactly once.
    """
    # Check for existing email (global uniqueness)
    existing = await session.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

    try:
        # 1. Create tenant
        tenant = Tenant(
            name=body.company_name,
            slug=_slugify(body.company_name),
            plan="free",
            credits_remaining=50,
            credits_monthly_limit=50,
            needs_profile_completion=False,
            needs_onboarding=True,
        )
        session.add(tenant)
        await session.flush()  # Get tenant.id without committing

        # 2. Create organization
        org = Organization(tenant_id=tenant.id, name=body.company_name)
        session.add(org)
        await session.flush()

        # 3. Create user
        verify_token_plain = secrets.token_urlsafe(32)
        verify_token_hash = hashlib.sha256(verify_token_plain.encode()).hexdigest()
        user = User(
            tenant_id=tenant.id,
            org_id=org.id,
            email=body.email,
            password_hash=hash_password(body.password),
            role="owner",
            email_verified=False,
            email_verify_token=verify_token_hash,
            email_verify_expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
        )
        session.add(user)
        await session.flush()

        session.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="admin"))
        await session.flush()

        # 4. Generate API key (store hash, return plaintext once)
        plaintext_key, key_hash, key_hint = generate_api_key()
        api_key = ApiKey(
            tenant_id=tenant.id,
            user_id=user.id,
            key_hash=key_hash,
            key_hint=key_hint,
            label="Default",
            scope=["*"],
        )
        session.add(api_key)

        # Seed default tag definitions for the new tenant
        await seed_default_tag_definitions(session, tenant.id)

        if body.invite_token:
            token_hash = _invite_token_hash(body.invite_token.strip())
            inv_row = await session.execute(
                select(TenantInvite).where(
                    TenantInvite.token_hash == token_hash,
                    TenantInvite.accepted_at.is_(None),
                )
            )
            inv = inv_row.scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if not inv or inv.expires_at < now:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired invite.")
            if inv.email.strip().lower() != body.email.strip().lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invite email does not match signup email.",
                )
            dup = await session.execute(
                select(TenantMembership).where(
                    TenantMembership.user_id == user.id,
                    TenantMembership.tenant_id == inv.tenant_id,
                )
            )
            if not dup.scalar_one_or_none():
                session.add(
                    TenantMembership(
                        user_id=user.id,
                        tenant_id=inv.tenant_id,
                        role=inv.role,
                    )
                )
            inv.accepted_at = now

        await session.commit()

        log.info("tenant_created", tenant_id=str(tenant.id), email=body.email)

        # Fire verification email async (non-blocking, don't fail signup if SES is down)
        verify_url = f"{settings.frontend_url}/verify-email?token={verify_token_plain}"
        asyncio.ensure_future(_send_verification_email_bg(body.email, verify_url))

        return SignupResponse(
            tenant_id=str(tenant.id),
            user_id=str(user.id),
            api_key=plaintext_key,
        )

    except Exception as e:
        await session.rollback()
        log.error("signup_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Signup failed.") from e


async def _send_verification_email_bg(email: str, verify_url: str) -> None:
    try:
        from apps.api.services.email_service import send_verify_email
        await send_verify_email(email, verify_url)
    except Exception as exc:
        log.warning("verify_email_send_failed", email=email, error=str(exc))


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_no_rls),
) -> LoginResponse:
    result = await session.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    if user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account uses Google sign-in.",
        )
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled.")

    summaries = await _tenant_summaries_for_user(session, user.id)
    if not summaries:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Account has no workspace memberships.",
        )

    by_id = {s.tenant_id: s for s in summaries}
    chosen: TenantSummary
    must_select = False
    if body.active_tenant_id:
        if body.active_tenant_id not in by_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not a member of that workspace.")
        chosen = by_id[body.active_tenant_id]
    else:
        home = str(user.tenant_id)
        chosen = by_id.get(home) or summaries[0]
        must_select = len(summaries) > 1

    tid_uuid = uuid.UUID(chosen.tenant_id)
    key_result = await session.execute(
        select(ApiKey).where(ApiKey.tenant_id == tid_uuid, ApiKey.is_active == True).limit(1)
    )
    default_key = key_result.scalar_one_or_none()

    token = create_access_token({"sub": str(user.id), "tenant_id": chosen.tenant_id})
    return LoginResponse(
        access_token=token,
        tenant_id=chosen.tenant_id,
        user_id=str(user.id),
        api_key_hint=default_key.key_hint if default_key else "****",
        tenants=summaries,
        must_select_tenant=must_select,
        membership_role=chosen.role,
    )


@router.get("/me", response_model=MeResponse)
async def auth_me(
    current: CurrentUser,
    session: AsyncSession = Depends(get_db_no_rls),
) -> MeResponse:
    user, active_tid, role = current
    summaries = await _tenant_summaries_for_user(session, user.id)
    result = await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(active_tid)))
    tenant = result.scalar_one_or_none()
    needs_profile = bool(tenant and tenant.needs_profile_completion and role == "admin")
    needs_onboarding = bool(tenant and tenant.needs_onboarding)
    return MeResponse(
        email=user.email,
        user_id=str(user.id),
        active_tenant_id=active_tid,
        membership_role=role,
        tenants=summaries,
        needs_tenant_profile=needs_profile,
        needs_onboarding=needs_onboarding,
        email_verified=user.email_verified,
    )


@router.post("/switch-tenant", response_model=SwitchTenantResponse)
async def switch_tenant(
    body: SwitchTenantRequest,
    current: CurrentUser,
    session: AsyncSession = Depends(get_db_no_rls),
) -> SwitchTenantResponse:
    user, _, _ = current
    try:
        tid = uuid.UUID(body.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant id.") from e
    m = await session.execute(
        select(TenantMembership).where(
            TenantMembership.user_id == user.id,
            TenantMembership.tenant_id == tid,
        )
    )
    mem = m.scalar_one_or_none()
    if not mem:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of that workspace.")
    token = create_access_token({"sub": str(user.id), "tenant_id": str(tid)})
    return SwitchTenantResponse(
        access_token=token,
        tenant_id=str(tid),
        membership_role=str(mem.role),
    )


class InviteAcceptRequest(BaseModel):
    token: str


@router.get("/invites/preview", response_model=InvitePreviewResponse)
async def preview_invite(
    token: str = Query(..., min_length=16),
    session: AsyncSession = Depends(get_db_no_rls),
) -> InvitePreviewResponse:
    th = _invite_token_hash(token.strip())
    r = await session.execute(select(TenantInvite).where(TenantInvite.token_hash == th))
    inv = r.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found.")
    tr = await session.execute(select(Tenant).where(Tenant.id == inv.tenant_id))
    t = tr.scalar_one_or_none()
    return InvitePreviewResponse(
        tenant_name=t.name if t else "",
        tenant_slug=t.slug if t else "",
        email=inv.email,
        role=str(inv.role),
        expired=inv.expires_at < now,
        accepted=inv.accepted_at is not None,
    )


@router.post("/invites/accept")
async def accept_invite(
    body: InviteAcceptRequest,
    current: CurrentUser,
    session: AsyncSession = Depends(get_db_no_rls),
) -> dict:
    user, _, _ = current
    th = _invite_token_hash(body.token.strip())
    r = await session.execute(
        select(TenantInvite).where(
            TenantInvite.token_hash == th,
            TenantInvite.accepted_at.is_(None),
        )
    )
    inv = r.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not inv or inv.expires_at < now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired invite.")
    if inv.email.strip().lower() != user.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite email does not match your account.",
        )
    dup = await session.execute(
        select(TenantMembership).where(
            TenantMembership.user_id == user.id,
            TenantMembership.tenant_id == inv.tenant_id,
        )
    )
    if not dup.scalar_one_or_none():
        session.add(
            TenantMembership(
                user_id=user.id,
                tenant_id=inv.tenant_id,
                role=inv.role,
            )
        )
    inv.accepted_at = now
    return {"status": "accepted", "tenant_id": str(inv.tenant_id)}


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(current: CurrentUser) -> list[ApiKeyResponse]:
    user, tenant_id, _ = current
    tid = uuid.UUID(tenant_id)
    from apps.api.core.database import get_session_with_tenant
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.tenant_id == tid, ApiKey.is_active == True)
        )
        keys = result.scalars().all()
    return [
        ApiKeyResponse(
            id=str(k.id),
            label=k.label,
            key_hint=k.key_hint,
            scope=k.scope,
            is_active=k.is_active,
            created_at=k.created_at.isoformat(),
        )
        for k in keys
    ]


@router.post("/api-keys", response_model=CreateApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(body: CreateApiKeyRequest, current: CurrentUser) -> CreateApiKeyResponse:
    user, tenant_id, _ = current
    plaintext_key, key_hash, key_hint = generate_api_key()
    from apps.api.core.database import get_session_with_tenant
    async with get_session_with_tenant(tenant_id) as session:
        api_key = ApiKey(
            tenant_id=uuid.UUID(tenant_id),
            user_id=user.id,
            key_hash=key_hash,
            key_hint=key_hint,
            label=body.label,
            scope=body.scope,
        )
        session.add(api_key)
    return CreateApiKeyResponse(id=str(api_key.id), api_key=plaintext_key, label=body.label, key_hint=key_hint)


@router.get("/google/enabled")
async def google_oauth_enabled() -> dict:
    """Public: whether Google sign-in is configured."""
    enabled = bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)
    return {"enabled": enabled}


@router.get("/google/login")
async def google_login() -> RedirectResponse:
    """Start Google OAuth — redirects to Google."""
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured.",
        )
    state = secrets.token_urlsafe(32)
    redis = get_redis()
    await redis.setex(f"google_oauth:{state}", 600, "1")

    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": _google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return RedirectResponse(url=url)


@router.get("/google/callback")
async def google_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    session: AsyncSession = Depends(get_db_no_rls),
) -> RedirectResponse:
    """OAuth redirect target — exchanges code, issues JWT, redirects to frontend."""
    base = settings.frontend_url.rstrip("/")
    if error:
        return RedirectResponse(url=f"{base}/callback?error={quote(error)}")
    if not code or not state:
        return RedirectResponse(url=f"{base}/callback?error=missing_params")

    redis = get_redis()
    if not await redis.get(f"google_oauth:{state}"):
        return RedirectResponse(url=f"{base}/callback?error=invalid_state")
    await redis.delete(f"google_oauth:{state}")

    try:
        profile = await _exchange_google_code(code)
        user = await _find_or_create_google_user(session, profile)
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "oauth_failed"
        return RedirectResponse(url=f"{base}/callback?error={quote(str(detail))}")

    if not user.is_active:
        return RedirectResponse(url=f"{base}/callback?error=account_disabled")

    summaries = await _tenant_summaries_for_user(session, user.id)
    if not summaries:
        return RedirectResponse(url=f"{base}/callback?error=no_memberships")

    by_id = {s.tenant_id: s for s in summaries}
    home = str(user.tenant_id)
    chosen = by_id.get(home) or summaries[0]
    must_select = len(summaries) > 1

    tid_uuid = uuid.UUID(chosen.tenant_id)
    key_result = await session.execute(
        select(ApiKey).where(ApiKey.tenant_id == tid_uuid, ApiKey.is_active == True).limit(1)
    )
    default_key = key_result.scalar_one_or_none()

    token = create_access_token({"sub": str(user.id), "tenant_id": chosen.tenant_id})
    q = urlencode(
        {
            "token": token,
            "tenant_id": chosen.tenant_id,
            "user_id": str(user.id),
            "api_key_hint": default_key.key_hint if default_key else "****",
            "must_select_tenant": "true" if must_select else "false",
            "membership_role": chosen.role,
        }
    )
    return RedirectResponse(url=f"{base}/callback?{q}")


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def revoke_api_key(key_id: str, current: CurrentUser) -> None:
    user, tenant_id, _ = current
    from apps.api.core.database import get_session_with_tenant
    async with get_session_with_tenant(tenant_id) as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.id == uuid.UUID(key_id), ApiKey.tenant_id == uuid.UUID(tenant_id))
        )
        key = result.scalar_one_or_none()
        if not key:
            raise HTTPException(status_code=404, detail="API key not found.")
        key.is_active = False


# ── Email verification ────────────────────────────────────────────────────────

class VerifyEmailRequest(BaseModel):
    token: str


@router.post("/verify-email")
async def verify_email(
    body: VerifyEmailRequest,
    session: AsyncSession = Depends(get_db_no_rls),
) -> dict:
    token_hash = hashlib.sha256(body.token.strip().encode()).hexdigest()
    result = await session.execute(
        select(User).where(User.email_verify_token == token_hash)
    )
    user = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not user or not user.email_verify_expires_at or user.email_verify_expires_at < now:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link.")
    if user.email_verified:
        return {"status": "already_verified"}
    user.email_verified = True
    user.email_verify_token = None
    user.email_verify_expires_at = None
    await session.commit()
    log.info("email_verified", user_id=str(user.id))

    # Send welcome email
    asyncio.ensure_future(_send_welcome_email_bg(user.email))
    return {"status": "verified"}


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    current: CurrentUser,
    session: AsyncSession = Depends(get_db_no_rls),
) -> dict:
    user, _tid, _role = current
    if user.email_verified:
        return {"status": "already_verified"}
    new_token_plain = secrets.token_urlsafe(32)
    new_token_hash = hashlib.sha256(new_token_plain.encode()).hexdigest()
    user.email_verify_token = new_token_hash
    user.email_verify_expires_at = datetime.now(timezone.utc) + timedelta(hours=48)
    await session.merge(user)
    await session.commit()
    verify_url = f"{settings.frontend_url}/verify-email?token={new_token_plain}"
    asyncio.ensure_future(_send_verification_email_bg(user.email, verify_url))
    return {"status": "sent"}


async def _send_welcome_email_bg(email: str) -> None:
    try:
        from apps.api.services.email_service import send_welcome_email
        await send_welcome_email(email)
    except Exception as exc:
        log.warning("welcome_email_send_failed", email=email, error=str(exc))


# ── Password reset ────────────────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        return v


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    body: ForgotPasswordRequest,
    session: AsyncSession = Depends(get_db_no_rls),
) -> dict:
    """Always returns 202 to prevent user enumeration."""
    result = await session.execute(select(User).where(User.email == body.email.lower().strip()))
    user = result.scalar_one_or_none()
    # Only proceed for manual (non-Google-only) accounts
    if user and user.password_hash:
        reset_token_plain = secrets.token_urlsafe(32)
        reset_token_hash = hashlib.sha256(reset_token_plain.encode()).hexdigest()
        user.password_reset_token = reset_token_hash
        user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        await session.merge(user)
        await session.commit()
        reset_url = f"{settings.frontend_url}/reset-password?token={reset_token_plain}"
        asyncio.ensure_future(_send_reset_email_bg(user.email, reset_url))
    return {"detail": "If this address is registered, you'll receive a link shortly."}


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    session: AsyncSession = Depends(get_db_no_rls),
) -> dict:
    token_hash = hashlib.sha256(body.token.strip().encode()).hexdigest()
    result = await session.execute(
        select(User).where(User.password_reset_token == token_hash)
    )
    user = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not user or not user.password_reset_expires_at or user.password_reset_expires_at < now:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")
    user.password_hash = hash_password(body.password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    await session.merge(user)
    await session.commit()
    log.info("password_reset", user_id=str(user.id))
    return {"status": "ok"}


async def _send_reset_email_bg(email: str, reset_url: str) -> None:
    try:
        from apps.api.services.email_service import send_reset_password_email
        await send_reset_password_email(email, reset_url)
    except Exception as exc:
        log.warning("reset_email_send_failed", email=email, error=str(exc))
