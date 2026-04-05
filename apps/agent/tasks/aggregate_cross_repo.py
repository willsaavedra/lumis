"""
Celery task: aggregate_cross_repo_patterns

Runs every Sunday at 03:00 UTC.
For each active tenant, aggregates findings from the last 30 days across all repos,
detects cross-repo patterns (same finding_type in ≥2 repos, dominant stack),
and upserts summary chunks into the tenant's knowledge index.
"""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import structlog

from apps.worker.celery_app import celery_app
from apps.agent.tasks.rag_shared import (
    embed_texts,
    upsert_chunks,
    delete_tenant_source_chunks,
)

log = structlog.get_logger(__name__)

# Cross-repo chunks expire after 10 days (refreshed weekly)
_CROSSREPO_EXPIRES_DAYS = 10


@celery_app.task(name="apps.agent.tasks.aggregate_cross_repo_patterns", bind=True, max_retries=1)
def aggregate_cross_repo_patterns(self) -> dict:
    """Weekly aggregation of cross-repo observability patterns per tenant."""
    log.info("aggregate_cross_repo_started")
    return asyncio.run(_run())


async def _run() -> dict:
    from sqlalchemy import select, and_, text
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.auth import Tenant
    from apps.api.models.scm import Repository

    async with AsyncSessionFactory() as session:
        tenants = (await session.execute(
            select(Tenant).where(Tenant.is_active == True)
        )).scalars().all()

    total_inserted = 0

    for tenant in tenants:
        try:
            inserted = await _aggregate_for_tenant(str(tenant.id))
            total_inserted += inserted
        except Exception as e:
            log.warning("crossrepo_tenant_failed", tenant_id=str(tenant.id), error=str(e))

    log.info("aggregate_cross_repo_complete", tenants=len(tenants), inserted=total_inserted)
    return {"tenants": len(tenants), "inserted": total_inserted}


async def _aggregate_for_tenant(tenant_id: str) -> int:
    from sqlalchemy import select, and_
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import AnalysisJob, AnalysisResult
    from apps.api.models.scm import Repository

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    async with AsyncSessionFactory() as session:
        # Get all completed jobs for this tenant in the last 30 days
        jobs = (await session.execute(
            select(AnalysisJob).where(
                and_(
                    AnalysisJob.tenant_id == __import__("uuid").UUID(tenant_id),
                    AnalysisJob.status == "completed",
                    AnalysisJob.completed_at >= cutoff,
                )
            )
        )).scalars().all()

        if not jobs:
            return 0

        job_ids = [j.id for j in jobs]
        repo_ids = list({str(j.repo_id) for j in jobs})

        # Load results
        results = (await session.execute(
            select(AnalysisResult).where(
                AnalysisResult.job_id.in_(job_ids)
            )
        )).scalars().all()

        # Load repo names
        repos = (await session.execute(
            select(Repository).where(
                Repository.id.in_([__import__("uuid").UUID(r) for r in repo_ids])
            )
        )).scalars().all()

    repo_name_map = {str(r.id): r.full_name for r in repos}
    repo_languages_map: dict[str, list[str]] = {
        str(r.id): list(r.language or []) for r in repos
    }

    # Collect all findings grouped by repo
    repo_findings: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        findings = result.findings or []
        if isinstance(findings, list):
            job = next((j for j in jobs if j.id == result.job_id), None)
            if job:
                repo_findings[str(job.repo_id)].extend(findings)

    if not repo_findings:
        return 0

    # Detect cross-repo patterns: same finding_type in >= 2 repos
    pattern_repos: dict[str, set[str]] = defaultdict(set)
    for repo_id, findings in repo_findings.items():
        for f in findings:
            key = f"{f.get('pillar', '')}:{f.get('title', '')[:50]}"
            pattern_repos[key].add(repo_id)

    cross_patterns = {k: v for k, v in pattern_repos.items() if len(v) >= 2}

    # Detect dominant stack
    all_languages: list[str] = []
    for repo_id in repo_ids:
        all_languages.extend(repo_languages_map.get(repo_id, []))
    lang_counter = Counter(all_languages)
    dominant_langs = [lang for lang, _ in lang_counter.most_common(3)]

    # Build summary chunks
    chunks_text = []

    if cross_patterns:
        patterns_text = "; ".join(
            f"'{k.split(':')[1]}' ({k.split(':')[0]}) found in {len(v)} repos"
            for k, v in list(cross_patterns.items())[:10]
        )
        chunks_text.append(
            f"CROSS-REPO PATTERN ALERT for tenant {tenant_id}: "
            f"The following observability gaps appear in multiple repositories: {patterns_text}. "
            f"These are systemic issues affecting the entire platform."
        )

    if dominant_langs:
        langs_str = ", ".join(dominant_langs)
        chunks_text.append(
            f"TENANT TECH STACK for tenant {tenant_id}: "
            f"The dominant programming languages across all repositories are: {langs_str}. "
            f"Suggest observability fixes using these languages."
        )

    repo_names = [v for v in repo_name_map.values()]
    if repo_names:
        repos_str = ", ".join(repo_names[:10])
        chunks_text.append(
            f"ACTIVE REPOSITORIES for tenant {tenant_id}: "
            f"This tenant has {len(repo_names)} active repositories including: {repos_str}. "
            f"Use this context to understand service dependencies."
        )

    if not chunks_text:
        return 0

    embeddings = await embed_texts(chunks_text)
    chunk_dicts = [
        {"content": c, "embedding": e, "metadata": {"tenant_id": tenant_id}}
        for c, e in zip(chunks_text, embeddings)
    ]

    # Invalidate previous cross-repo chunks for this tenant
    await delete_tenant_source_chunks(tenant_id, "cross_repo_pattern")

    return await upsert_chunks(
        chunk_dicts,
        tenant_id=tenant_id,
        source_type="cross_repo_pattern",
        expires_days=_CROSSREPO_EXPIRES_DAYS,
    )
