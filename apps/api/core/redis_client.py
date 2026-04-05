"""Redis client for caching, pub/sub, and session management."""
from __future__ import annotations

import redis.asyncio as aioredis

from apps.api.core.config import settings


def get_redis() -> aioredis.Redis:
    return aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )


def tenant_key(tenant_id: str, key: str) -> str:
    """All Redis keys for a tenant must be prefixed this way."""
    return f"t:{tenant_id}:{key}"
