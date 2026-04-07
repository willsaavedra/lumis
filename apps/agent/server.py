"""Horion Agent HTTP server.

All inter-service communication goes through this API.
The worker and API never import agent internals directly.

Endpoints:
  GET  /health
  POST /analyze/{job_id}           — trigger analysis (called by worker)
  POST /events/{job_id}            — emit a progress event (called by any service)
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = structlog.get_logger(__name__)

app = FastAPI(title="Horion Agent", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "horion-agent"}


@app.post("/analyze/{job_id}")
async def trigger_analysis(job_id: str) -> JSONResponse:
    """
    Trigger analysis for a job. Called by the Celery worker.
    Returns 202 immediately — the graph runs in a background task and
    publishes progress to Redis pub/sub + persistent timeline.
    """
    from apps.agent.graph import run_analysis_graph

    async def _run() -> None:
        try:
            await run_analysis_graph(job_id)
        except Exception:
            log.exception("run_analysis_graph_task_failed", job_id=job_id)

    asyncio.create_task(_run())
    return JSONResponse({"status": "started", "job_id": job_id}, status_code=202)


class EmitEventRequest(BaseModel):
    tenant_id: str
    stage: str
    progress_pct: int = 0
    message: str
    event_type: str = "step"
    extra: dict[str, Any] | None = None


@app.post("/events/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def emit_event(job_id: str, body: EmitEventRequest) -> None:
    """
    Emit a progress event for a job.
    Called by any service (worker, API) that needs to publish a status update
    without importing agent internals.

    The event is published to Redis pub/sub and appended to the persistent
    timeline so SSE clients can replay on reconnect.
    """
    try:
        from apps.agent.nodes.base import publish_analysis_event

        await publish_analysis_event(
            job_id,
            body.tenant_id,
            body.stage,
            body.progress_pct,
            body.message,
            event_type=body.event_type,
            extra=body.extra,
        )
    except Exception as exc:
        log.error("emit_event_failed", job_id=job_id, error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to emit event") from exc
