"""Shared tag filter parsing for analytics and analyses endpoints."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from apps.api.models.analysis import AnalysisJob
from apps.api.models.tag_system import AnalysisTag


def parse_tag_filter(tags_raw: str | None) -> list[tuple[str, str]]:
    """Parse '?tags=team:payments,env:production' into list of (key, value)."""
    if not tags_raw or not tags_raw.strip():
        return []
    pairs: list[tuple[str, str]] = []
    for token in tags_raw.split(","):
        token = token.strip()
        if ":" not in token:
            continue
        k, v = token.split(":", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            pairs.append((k, v))
    return pairs


def tag_filter_exists_clauses(tag_pairs: list[tuple[str, str]], tid: uuid.UUID):
    """Build AND EXISTS clauses on analysis_tags for each tag pair."""
    clauses = []
    for k, v in tag_pairs:
        sub = select(AnalysisTag.id).where(
            AnalysisTag.job_id == AnalysisJob.id,
            AnalysisTag.tenant_id == tid,
            AnalysisTag.key == k,
            AnalysisTag.value == v,
        ).correlate(AnalysisJob).exists()
        clauses.append(sub)
    return clauses
