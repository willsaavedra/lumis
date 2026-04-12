"""
Celery task: ingest_findings_snapshot

Triggered by post_report_node after every completed analysis.
Embeds ALL warning/critical findings into the RAG index (replacing the previous
snapshot for the same repo) so that future analyses can reference historical findings
even without user feedback.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from apps.worker.celery_app import celery_app
from apps.agent.tasks.rag_shared import embed_texts, upsert_chunks, delete_repo_source_chunks

log = structlog.get_logger(__name__)

_SNAPSHOT_EXPIRES_DAYS = 60
_SOURCE_TYPE = "findings_snapshot"


@celery_app.task(name="apps.agent.tasks.ingest_findings_snapshot", bind=True, max_retries=2)
def ingest_findings_snapshot(self, job_id: str) -> dict:
    """Ingest all warning/critical findings from a completed analysis into the RAG index."""
    log.info("ingest_findings_snapshot_started", job_id=job_id)
    return asyncio.run(_run(job_id))


async def _run(job_id: str) -> dict:
    from sqlalchemy import select
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob, AnalysisResult
    from apps.api.models.scm import Repository

    async with AsyncSessionFactory() as session:
        job = (await session.execute(
            select(AnalysisJob).where(AnalysisJob.id == __import__("uuid").UUID(job_id))
        )).scalar_one_or_none()
        if not job:
            log.warning("snapshot_job_not_found", job_id=job_id)
            return {"status": "skipped"}

        result = (await session.execute(
            select(AnalysisResult).where(AnalysisResult.job_id == job.id)
        )).scalar_one_or_none()
        if not result or not result.findings:
            return {"status": "skipped", "reason": "no_results"}

        repo = (await session.execute(
            select(Repository).where(Repository.id == job.repo_id)
        )).scalar_one_or_none()

    tenant_id = str(job.tenant_id)
    repo_id = str(job.repo_id)
    repo_language = (repo.language[0].lower() if repo and repo.language else None)

    findings = result.findings if isinstance(result.findings, list) else []
    relevant = [
        f for f in findings
        if f.get("severity") in ("critical", "warning")
        and f.get("confidence", "medium") != "low"
    ]

    if not relevant:
        log.info("snapshot_no_relevant_findings", job_id=job_id)
        return {"inserted": 0}

    # Delete previous snapshot for this repo before inserting new one
    deleted = await delete_repo_source_chunks(repo_id, _SOURCE_TYPE)
    log.info("snapshot_previous_deleted", repo_id=repo_id, deleted=deleted)

    chunks_text = [_build_finding_chunk(f, repo_id) for f in relevant]
    embeddings = await embed_texts(chunks_text)

    chunk_dicts = [
        {
            "content": text,
            "embedding": emb,
            "metadata": {
                "repo_id": repo_id,
                "file_path": f.get("file_path"),
                "language": repo_language,
                "pillar": f.get("pillar"),
                "severity": f.get("severity"),
                "finding_type": f.get("title", "")[:50],
                "snapshot_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        for f, text, emb in zip(relevant, chunks_text, embeddings)
    ]

    inserted = await upsert_chunks(
        chunk_dicts,
        tenant_id=tenant_id,
        source_type=_SOURCE_TYPE,
        repo_id=repo_id,
        language=repo_language,
        expires_days=_SNAPSHOT_EXPIRES_DAYS,
    )

    log.info(
        "snapshot_complete",
        job_id=job_id,
        findings_total=len(findings),
        findings_relevant=len(relevant),
        inserted=inserted,
    )
    return {"inserted": inserted, "relevant": len(relevant)}


def _build_finding_chunk(finding: dict, repo_id: str) -> str:
    parts = [
        f"Finding in repository {repo_id}:",
        f"  Pillar: {finding.get('pillar')} | Severity: {finding.get('severity')} | Dimension: {finding.get('dimension')}",
        f"  Title: {finding.get('title')}",
        f"  Description: {finding.get('description', '')[:500]}",
    ]
    if finding.get("file_path"):
        loc = f"  File: {finding['file_path']}"
        if finding.get("line_start"):
            loc += f" line {finding['line_start']}"
        parts.append(loc)
    if finding.get("suggestion"):
        parts.append(f"  Suggested fix: {finding['suggestion'][:300]}")
    return "\n".join(parts)
