"""LangGraph agent HTTP server — exposes analysis trigger endpoint."""
from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from apps.agent.core.config import settings
from apps.agent.core.logging import configure_logging

configure_logging()

app = FastAPI(title="Lumis Agent", version="0.1.0")
log = structlog.get_logger(__name__)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "lumis-agent"}


@app.post("/analyze/{job_id}")
async def trigger_analysis(job_id: str) -> JSONResponse:
    """
    Trigger analysis for a job. Called by the Celery worker.
    Returns immediately — progress is published to Redis pub/sub.
    """
    import asyncio
    from apps.agent.graph import run_analysis_graph

    asyncio.create_task(run_analysis_graph(job_id))
    return JSONResponse({"status": "started", "job_id": job_id})
