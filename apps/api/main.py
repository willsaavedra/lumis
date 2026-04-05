"""Lumis API — FastAPI application entry point."""
from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.core.config import settings
from apps.api.core.logging import configure_logging
from apps.api.routers import auth, repositories, analyses, billing, connections, webhooks, stripe_webhooks, tenant, team
from apps.api.routers.vendors import router as vendors_router
from apps.api.routers.rag import router as rag_router

configure_logging()
log = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Lumis API",
        description="AI-powered SRE observability platform",
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Public endpoints
    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
    app.include_router(stripe_webhooks.router, prefix="/webhooks", tags=["stripe"])
    app.include_router(connections.router, prefix="/connect", tags=["connections"])

    # API v1
    app.include_router(repositories.router, prefix="/api/v1/repositories", tags=["repositories"])
    app.include_router(analyses.router, prefix="/api/v1/analyses", tags=["analyses"])
    app.include_router(billing.router, prefix="/api/v1/billing", tags=["billing"])
    app.include_router(tenant.router, prefix="/api/v1/tenant", tags=["tenant"])
    app.include_router(team.router, prefix="/api/v1/team", tags=["team"])
    app.include_router(vendors_router, prefix="/api/v1/vendors", tags=["vendors"])
    app.include_router(rag_router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "service": "lumis-api"}

    @app.get("/ready", tags=["health"])
    async def ready() -> dict:
        return {"status": "ready"}

    @app.on_event("startup")
    async def startup() -> None:
        log.info("lumis_api_started", env=settings.env, debug=settings.debug)

    return app


app = create_app()
