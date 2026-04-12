"""Authentication, API key management, and JWT utilities."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import structlog
from jose import JWTError, jwt
from passlib.context import CryptContext
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from apps.api.core.config import settings

log = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


def hash_password(password: str) -> str:
    prehashed = hashlib.sha256(password.encode()).hexdigest()
    return pwd_context.hash(prehashed)


def verify_password(plain: str, hashed: str) -> bool:
    prehashed = hashlib.sha256(plain.encode()).hexdigest()
    return pwd_context.verify(prehashed, hashed)


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.
    Returns (plaintext_key, key_hash, key_hint)
    The plaintext key must be shown once and never stored.
    """
    raw = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(f"{settings.api_key_salt}:{raw}".encode()).hexdigest()
    key_hint = raw[-4:]
    return raw, key_hash, key_hint


def hash_api_key(plaintext: str) -> str:
    return hashlib.sha256(f"{settings.api_key_salt}:{plaintext}".encode()).hexdigest()


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


def create_state_token(tenant_id: str, user_id: str) -> str:
    """Short-lived state token for OAuth/GitHub App flows."""
    return jwt.encode(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            "nonce": secrets.token_hex(8),
        },
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def decode_state_token(token: str) -> dict:
    with tracer.start_as_current_span("decode_state_token") as span:
        try:
            return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        except JWTError as e:
            span.record_exception(e)
            span.set_status(StatusCode.ERROR, str(e))
            log.error("jwt_decode_failed", exc_info=True)
            raise ValueError(f"Invalid state token: {e}") from e


def verify_hmac_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub/GitLab webhook HMAC-SHA256 signature."""
    expected = "sha256=" + hmac.new(secret.encode(), payload, "sha256").hexdigest()
    return hmac.compare_digest(expected, signature)


def _scm_fernet():
    """Fernet key derived from app secret (32 url-safe bytes)."""
    from base64 import urlsafe_b64encode
    from cryptography.fernet import Fernet

    key = urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(key)


def encrypt_scm_token(plaintext: str) -> bytes:
    """Encrypt OAuth / PAT tokens for scm_connections.encrypted_token."""
    return _scm_fernet().encrypt(plaintext.encode())


def decrypt_scm_token(blob: bytes | None) -> str | None:
    if not blob:
        return None
    with tracer.start_as_current_span("decrypt_scm_token") as span:
        try:
            return _scm_fernet().decrypt(blob).decode()
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, str(exc))
            log.error("scm_token_decrypt_failed", exc_info=True)
            return None