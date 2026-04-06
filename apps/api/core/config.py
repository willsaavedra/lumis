"""Application configuration via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    env: Literal["local", "staging", "production"] = "local"
    debug: bool = False
    log_level: str = "info"
    secret_key: str = Field(min_length=32)
    api_key_salt: str = Field(min_length=32)
    allowed_origins: list[str] = ["http://localhost:3000"]

    # Database
    database_url: str = "postgresql+asyncpg://sre:local_only@postgres:5432/lumis"

    # Redis
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # S3 / MinIO
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_bucket_name: str = "lumis"
    s3_region: str = "us-east-1"

    # Anthropic (LLM generation)
    anthropic_api_key: str = ""
    anthropic_model_primary: str = "claude-sonnet-4-20250514"
    anthropic_model_triage: str = "claude-haiku-4-5-20251001"

    # CerebraAI — OpenAI-compatible vLLM (Qwen self-hosted)
    cerebra_ai_base_url: str = "http://52.86.35.131:8001/v1"
    cerebra_ai_api_key: str = ""
    cerebra_ai_model_primary: str = "Qwen/Qwen3.5-35B-A3B-FP8"
    cerebra_ai_model_triage: str = "Qwen/Qwen3.5-35B-A3B-FP8"
    cerebra_ai_temperature: float = 0.4
    cerebra_ai_top_p: float = 0.9
    cerebra_ai_timeout: int = 300

    # OpenAI — used only for text embeddings (RAG: knowledge_chunks + retrieve_context)
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    # Optional: Azure OpenAI or compatible proxy (e.g. https://xxx.openai.azure.com/openai/v1)
    openai_base_url: str | None = None

    @field_validator("openai_base_url", mode="before")
    @classmethod
    def _empty_openai_base_url(cls, v: object) -> str | None:
        if v is None or v == "":
            return None
        return str(v)

    # GitHub App
    github_app_id: str = ""
    github_app_slug: str = "lumis"
    github_app_private_key_path: str = ""
    github_webhook_secret: str = ""

    # GitLab OAuth (https://gitlab.com/-/profile/applications)
    gitlab_app_id: str = ""
    gitlab_app_secret: str = ""
    gitlab_webhook_secret: str = ""
    gitlab_base_url: str = "https://gitlab.com"

    # Bitbucket Cloud OAuth (https://support.atlassian.com/bitbucket-cloud/docs/use-oauth-on-bitbucket-cloud/)
    bitbucket_client_id: str = ""
    bitbucket_client_secret: str = ""

    # Datadog
    dd_api_key: str = ""
    dd_app_key: str = ""
    dd_site: str = "datadoghq.com"

    # Stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_meter_id: str = ""
    stripe_price_starter_base: str = ""
    stripe_price_starter_overage: str = ""
    stripe_price_growth_base: str = ""
    stripe_price_growth_overage: str = ""
    stripe_price_scale_base: str = ""
    stripe_price_scale_overage: str = ""

    # Slack
    slack_webhook_url: str = ""

    # Plan credit limits
    plan_credits: dict[str, int] = {
        "free": 50,
        "starter": 300,
        "growth": 1000,
        "scale": 5000,
        "enterprise": 999999,
    }

    # Analysis credit costs
    analysis_credits: dict[str, int] = {
        "quick": 1,
        "full": 3,
        "repository": 15,
    }

    # TS Agent service
    ts_agent_url: str = "http://agent-ts:3000"

    api_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # Google OAuth (Sign in with Google) — leave empty to disable
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = ""  # default: {api_base_url}/auth/google/callback

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
