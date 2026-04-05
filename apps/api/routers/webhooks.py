"""SCM webhook endpoints (GitHub, GitLab)."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from apps.api.core.config import settings
from apps.api.core.security import verify_hmac_signature

log = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
) -> dict:
    """
    Receive GitHub webhook events. Verifies HMAC signature, then enqueues analysis.
    Returns 202 immediately — processing happens asynchronously.
    """
    payload_bytes = await request.body()

    # Verify webhook signature
    if settings.github_webhook_secret:
        if not x_hub_signature_256:
            raise HTTPException(status_code=401, detail="Missing webhook signature.")
        if not verify_hmac_signature(payload_bytes, x_hub_signature_256, settings.github_webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    payload = await request.json()
    event = x_github_event or "unknown"
    delivery_id = x_github_delivery or "unknown"

    log.info("github_webhook_received", event=event, delivery_id=delivery_id)

    # Only process pull_request events
    if event not in ("pull_request", "push"):
        return {"status": "ignored", "event": event}

    # Enqueue background processing
    background_tasks.add_task(_process_github_webhook, payload, event, delivery_id)
    return {"status": "accepted", "delivery_id": delivery_id}


async def _process_github_webhook(payload: dict, event: str, delivery_id: str) -> None:
    """
    Process GitHub webhook payload asynchronously.
    Finds the matching repo, checks billing, and enqueues Celery task.
    """
    try:
        from apps.api.core.database import db_session_no_rls
        from apps.api.services.analysis_service import enqueue_analysis_from_webhook
        from apps.api.scm.github import GitHubAdapter

        adapter = GitHubAdapter()
        analysis_request = adapter.normalize_event(payload, event)
        if analysis_request is None:
            log.info("github_webhook_skipped", reason="Not an analysis-triggering event", delivery_id=delivery_id)
            return

        async with db_session_no_rls() as session:
            await enqueue_analysis_from_webhook(session, analysis_request)

    except Exception as e:
        log.error("github_webhook_processing_failed", error=str(e), delivery_id=delivery_id)


@router.post("/gitlab", status_code=status.HTTP_202_ACCEPTED)
async def gitlab_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_gitlab_token: str | None = Header(default=None),
    x_gitlab_event: str | None = Header(default=None),
) -> dict:
    """GitLab webhook handler."""
    if settings.gitlab_webhook_secret and x_gitlab_token != settings.gitlab_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook token.")

    payload = await request.json()
    log.info("gitlab_webhook_received", event=x_gitlab_event)
    # TODO: Implement GitLab webhook processing similar to GitHub
    return {"status": "accepted"}
