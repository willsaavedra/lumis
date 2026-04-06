"""Lumis API — FastAPI application entry point."""
from __future__ import annotations

import time
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from apps.api.core.config import settings
from apps.api.core.logging import configure_logging
from apps.api.routers import auth, repositories, analyses, billing, connections, webhooks, stripe_webhooks, tenant, team
from apps.api.routers.vendors import router as vendors_router
from apps.api.routers.rag import router as rag_router

configure_logging()
log = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log each HTTP request as a structured JSON event."""

    _SKIP_PATHS = frozenset({"/health", "/ready", "/docs", "/redoc", "/openapi.json"})

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._SKIP_PATHS:
            return await call_next(request)

        request_id = str(uuid.uuid4())
        t0 = time.monotonic()

        # Make request_id available downstream (e.g. in routers)
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)

        duration_ms = round((time.monotonic() - t0) * 1000)
        tenant_id = getattr(request.state, "tenant_id", None)

        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            tenant_id=tenant_id,
            request_id=request_id,
        )

        # Clear per-request contextvars so they don't bleed into the next request
        structlog.contextvars.unbind_contextvars("request_id")

        return response


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
    app.add_middleware(RequestLoggingMiddleware)

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
