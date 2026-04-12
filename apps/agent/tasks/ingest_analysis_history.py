"""
Celery task: ingest_analysis_history

Triggered by post_report_node after each completed analysis.
Ingests confirmed findings (applied suggestions + thumbs_down false positives)
into the per-tenant knowledge index to power the feedback flywheel.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from apps.worker.celery_app import celery_app
from apps.agent.tasks.rag_shared import embed_texts, upsert_chunks

log = structlog.get_logger(__name__)

# History chunks expire in 90 days
_HISTORY_EXPIRES_DAYS = 90


@celery_app.task(name="apps.agent.tasks.ingest_analysis_history", bind=True, max_retries=2)
def ingest_analysis_history(self, job_id: str) -> dict:
    """
    After an analysis completes, ingest confirmed findings into the tenant's knowledge index.
    - applied + thumbs_up (suggestion) → confirmed true positive → ingest as positive example
    - thumbs_down (finding)            → confirmed false positive → ingest with do_not_report tag
    """
    log.info("ingest_analysis_history_started", job_id=job_id)
    return asyncio.run(_run(job_id))


async def _run(job_id: str) -> dict:
    from sqlalchemy import select, text
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob, AnalysisResult, FindingFeedback, Finding

    async with AsyncSessionFactory() as session:
        job = (await session.execute(
            select(AnalysisJob).where(AnalysisJob.id == __import__("uuid").UUID(job_id))
        )).scalar_one_or_none()
        if not job:
            log.warning("ingest_history_job_not_found", job_id=job_id)
            return {"status": "skipped"}

        result = (await session.execute(
            select(AnalysisResult).where(AnalysisResult.job_id == job.id)
        )).scalar_one_or_none()
        if not result:
            return {"status": "skipped"}

        # Load all feedback for findings in this job
        feedback_rows = (await session.execute(
            select(FindingFeedback, Finding)
            .join(Finding, Finding.id == FindingFeedback.finding_id)
            .where(FindingFeedback.job_id == job.id)
        )).all()

    tenant_id = str(job.tenant_id)
    repo_id = str(job.repo_id)

    # Load the repo language for correct embedding metadata
    from apps.api.models.scm import Repository
    repo_language: str | None = None
    async with AsyncSessionFactory() as session:
        repo = (await session.execute(
            select(Repository).where(Repository.id == job.repo_id)
        )).scalar_one_or_none()
        if repo and repo.language:
            repo_language = repo.language[0].lower()

    tp_chunks = []
    fp_chunks = []

    for fb, finding in feedback_rows:
        chunk_text = _build_finding_chunk(finding, repo_id)

        if fb.signal in ("applied", "thumbs_up") and fb.target_type == "finding":
            tp_chunks.append({
                "text": chunk_text,
                "metadata": {
                    "repo_id": repo_id,
                    "file_path": finding.file_path,
                    "language": repo_language,
                    "pillar": finding.pillar,
                    "finding_type": finding.title[:50],
                    "signal": fb.signal,
                    "confirmed_at": datetime.now(timezone.utc).isoformat(),
                },
            })
        elif fb.signal == "thumbs_down" and fb.target_type == "finding":
            fp_chunks.append({
                "text": chunk_text + "\n[DO NOT REPORT: This was a false positive for this codebase]",
                "metadata": {
                    "repo_id": repo_id,
                    "file_path": finding.file_path,
                    "language": repo_language,
                    "pillar": finding.pillar,
                    "finding_type": finding.title[:50],
                    "do_not_report": True,
                    "confirmed_at": datetime.now(timezone.utc).isoformat(),
                },
            })

    if not tp_chunks and not fp_chunks:
        log.info("ingest_history_no_feedback_to_ingest", job_id=job_id)
        return {"inserted": 0}

    all_chunks = tp_chunks + fp_chunks
    all_texts = [c["text"] for c in all_chunks]
    embeddings = await embed_texts(all_texts)

    chunk_dicts = [
        {
            "content": c["text"],
            "embedding": e,
            "metadata": c["metadata"],
        }
        for c, e in zip(all_chunks, embeddings)
    ]

    inserted = await upsert_chunks(
        chunk_dicts,
        tenant_id=tenant_id,
        source_type="analysis_history",
        repo_id=repo_id,
        language=repo_language,
        expires_days=_HISTORY_EXPIRES_DAYS,
    )

    log.info(
        "ingest_history_complete",
        job_id=job_id,
        tp=len(tp_chunks),
        fp=len(fp_chunks),
        inserted=inserted,
    )
    return {"inserted": inserted, "tp": len(tp_chunks), "fp": len(fp_chunks)}


def _build_finding_chunk(finding, repo_id: str) -> str:
    """Build a descriptive text chunk for a finding (for embedding)."""
    parts = [
        f"Finding in repository {repo_id}:",
        f"  Pillar: {finding.pillar} | Severity: {finding.severity} | Dimension: {finding.dimension}",
        f"  Title: {finding.title}",
        f"  Description: {finding.description}",
    ]
    if finding.file_path:
        parts.append(f"  File: {finding.file_path}" + (f" line {finding.line_start}" if finding.line_start else ""))
    if finding.suggestion:
        parts.append(f"  Suggested fix: {finding.suggestion[:300]}")
    return "\n".join(parts)
