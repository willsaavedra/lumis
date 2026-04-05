"""Agent configuration."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["local", "staging", "production"] = "local"
    debug: bool = False
    log_level: str = "info"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model_primary: str = "claude-sonnet-4-20250514"
    anthropic_model_triage: str = "claude-haiku-4-5-20251001"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # S3 / MinIO
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_bucket_name: str = "lumis"
    s3_region: str = "us-east-1"

    # Database
    database_url: str = "postgresql+asyncpg://sre:local_only@postgres:5432/lumis"

    # Datadog (optional)
    dd_api_key: str = ""
    dd_app_key: str = ""
    dd_site: str = "datadoghq.com"


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()


settings = get_settings()
