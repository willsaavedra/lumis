"""Tag validation and analysis-tag snapshot logic."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.tag_system import AnalysisTag, RepoTag, TagDefinition

log = structlog.get_logger(__name__)

_BRANCH_REF_PREFIX = re.compile(r"^refs/heads/")


def _extract_branch_name(ref: str) -> str:
    return _BRANCH_REF_PREFIX.sub("", ref) if ref else "unknown"


@dataclass
class TagInput:
    key: str
    value: str


@dataclass
class TagValidationError:
    key: str
    message: str
    level: str = "error"  # "error" | "warning"


@dataclass
class TagValidationResult:
    valid: bool
    errors: list[TagValidationError] = field(default_factory=list)
    warnings: list[TagValidationError] = field(default_factory=list)


async def validate_repo_tags(
    session: AsyncSession,
    tenant_id: str,
    tags: list[TagInput],
) -> list[TagValidationError]:
    """
    Validate tags against tenant's tag_definitions.
    Returns list of errors (empty = valid).
    """
    tid = uuid.UUID(tenant_id)
    defs_result = await session.execute(
        select(TagDefinition).where(TagDefinition.tenant_id == tid)
    )
    definitions = {d.key: d for d in defs_result.scalars().all()}

    issues: list[TagValidationError] = []
    provided_keys = {t.key for t in tags}

    for t in tags:
        defn = definitions.get(t.key)
        if defn is None:
            issues.append(TagValidationError(key=t.key, message=f"Unknown tag key '{t.key}'.", level="warning"))
            continue
        if defn.allowed_values and t.value not in defn.allowed_values:
            issues.append(
                TagValidationError(
                    key=t.key,
                    message=f"Value '{t.value}' is not allowed for '{t.key}'. Allowed: {', '.join(defn.allowed_values)}",
                    level="error",
                )
            )

    if tags:
        for key, defn in definitions.items():
            if defn.required and key not in provided_keys:
                issues.append(
                    TagValidationError(key=key, message=f"Required tag '{key}' is missing.", level="error")
                )

    return issues


async def validate_and_warn(
    session: AsyncSession,
    tenant_id: str,
    tags: list[TagInput],
) -> TagValidationResult:
    """Validate and split into errors (block save) and warnings (informational)."""
    issues = await validate_repo_tags(session, tenant_id, tags)
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    return TagValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


async def snapshot_tags_for_job(
    session: AsyncSession,
    tenant_id: str,
    job_id: uuid.UUID,
    repo_id: uuid.UUID,
    trigger: str,
    ref: str,
    pr_number: int | None,
    analysis_type: str,
) -> None:
    """
    Copy current repo_tags into analysis_tags for a job, then add system tags.
    Must run inside the same transaction that created the analysis_job row.
    """
    tid = uuid.UUID(tenant_id)

    repo_tags_result = await session.execute(
        select(RepoTag.key, RepoTag.value, RepoTag.source).where(
            RepoTag.repo_id == repo_id,
            RepoTag.tenant_id == tid,
        )
    )

    rows: list[dict] = []
    for key, value, source in repo_tags_result.all():
        rows.append({"key": key, "value": value, "source": source})

    rows.append({"key": "trigger", "value": trigger, "source": "system"})
    rows.append({"key": "branch", "value": _extract_branch_name(ref), "source": "system"})
    rows.append({"key": "type", "value": analysis_type, "source": "system"})
    if pr_number is not None:
        rows.append({"key": "pr", "value": str(pr_number), "source": "system"})

    for r in rows:
        session.add(
            AnalysisTag(
                tenant_id=tid,
                job_id=job_id,
                key=r["key"],
                value=r["value"],
                source=r["source"],
            )
        )
    await session.flush()

    log.info(
        "analysis_tags_snapshot_created",
        job_id=str(job_id),
        tag_count=len(rows),
    )


DEFAULT_TAG_DEFINITIONS = [
    {
        "key": "team",
        "label": "Squad / Team",
        "description": "Which team owns this repository",
        "required": True,
        "allowed_values": None,
        "color_class": "tag-team",
        "sort_order": 1,
    },
    {
        "key": "env",
        "label": "Environment",
        "description": "Deployment environment",
        "required": True,
        "allowed_values": ["production", "staging", "dev", "sandbox"],
        "color_class": "tag-env",
        "sort_order": 2,
    },
    {
        "key": "criticality",
        "label": "Business Criticality",
        "description": "How critical this service is to the business",
        "required": True,
        "allowed_values": ["critical", "high", "medium", "low"],
        "color_class": "tag-criticality",
        "sort_order": 3,
    },
    {
        "key": "domain",
        "label": "Business Domain",
        "description": "Business domain this service belongs to",
        "required": False,
        "allowed_values": None,
        "color_class": "tag-domain",
        "sort_order": 4,
    },
    {
        "key": "cost-center",
        "label": "Cost Center",
        "description": "Cost allocation center",
        "required": False,
        "allowed_values": None,
        "color_class": "tag-cost-center",
        "sort_order": 5,
    },
    {
        "key": "lang",
        "label": "Language",
        "description": "Primary programming language (auto-detected by agent)",
        "required": False,
        "allowed_values": ["go", "python", "java", "node", "typescript", "ruby", "rust"],
        "color_class": "tag-service",
        "sort_order": 6,
    },
]


async def seed_default_tag_definitions(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Insert the 6 default tag definitions for a new tenant."""
    for defn in DEFAULT_TAG_DEFINITIONS:
        session.add(
            TagDefinition(
                tenant_id=tenant_id,
                key=defn["key"],
                label=defn["label"],
                description=defn["description"],
                required=defn["required"],
                allowed_values=defn["allowed_values"],
                color_class=defn["color_class"],
                sort_order=defn["sort_order"],
            )
        )
    await session.flush()
