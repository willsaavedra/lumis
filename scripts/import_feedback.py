#!/usr/bin/env python3
"""
Lumis Feedback → Eval Dataset Importer
========================================
Reads thumbs_down and applied feedback signals from the DB and exports them
as annotated YAML eval cases, feeding the tuning flywheel.

Usage:
    python scripts/import_feedback.py --since 7d
    python scripts/import_feedback.py --since 30d --signal thumbs_down
    python scripts/import_feedback.py --dry-run

Output:
    eval/cases/<language>/feedback_<id>.yaml  — one file per finding
    Prints a summary of exported cases.

Flow:
    thumbs_down → expected_no_findings (false positive case)
    applied     → expected_findings    (confirmed true positive case)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

EVAL_DIR = REPO_ROOT / "eval" / "cases"


def _parse_since(since: str) -> datetime:
    """Parse a duration string like '7d', '30d', '24h' into a UTC datetime."""
    since = since.strip().lower()
    if since.endswith("d"):
        delta = timedelta(days=int(since[:-1]))
    elif since.endswith("h"):
        delta = timedelta(hours=int(since[:-1]))
    else:
        raise ValueError(f"Unsupported since format: {since!r} (use 7d, 30d, 24h)")
    return datetime.now(timezone.utc) - delta


def _language_for_path(file_path: str | None) -> str:
    if not file_path:
        return "unknown"
    ext_map = {
        ".go": "go",
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".java": "java",
        ".tf": "terraform",
        ".hcl": "terraform",
        ".yaml": "yaml",
        ".yml": "yaml",
    }
    for ext, lang in ext_map.items():
        if file_path.endswith(ext):
            return lang
    return "unknown"


def _category_slug(title: str) -> str:
    """Convert a finding title to a snake_case category slug."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower().strip())
    return slug[:60].strip("_")


async def export_feedback(
    since: datetime,
    signal_filter: str | None,
    dry_run: bool,
) -> int:
    """Query the DB for feedback and write YAML eval cases. Returns number exported."""
    from sqlalchemy import select
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.models.analysis import Finding, FindingFeedback, AnalysisJob, AnalysisResult

    exported = 0
    async with AsyncSessionFactory() as session:
        query = (
            select(
                FindingFeedback.id,
                FindingFeedback.signal,
                FindingFeedback.note,
                FindingFeedback.feedback_at,
                FindingFeedback.tenant_id,
                Finding.id.label("finding_id"),
                Finding.title,
                Finding.description,
                Finding.pillar,
                Finding.severity,
                Finding.dimension,
                Finding.file_path,
                Finding.line_start,
                Finding.line_end,
                Finding.suggestion,
                AnalysisJob.id.label("job_id"),
            )
            .join(Finding, FindingFeedback.finding_id == Finding.id)
            .join(AnalysisResult, Finding.result_id == AnalysisResult.id)
            .join(AnalysisJob, AnalysisResult.job_id == AnalysisJob.id)
            .where(FindingFeedback.feedback_at >= since)
            .where(FindingFeedback.signal.in_(["thumbs_down", "applied"]))
        )
        if signal_filter:
            query = query.where(FindingFeedback.signal == signal_filter)

        result = await session.execute(query)
        rows = result.all()

    print(f"Found {len(rows)} feedback signals since {since.strftime('%Y-%m-%d %H:%M UTC')}")

    for row in rows:
        language = _language_for_path(row.file_path)
        category = _category_slug(row.title)
        case_id = f"feedback-{str(row.id)[:8]}"

        if row.signal == "thumbs_down":
            # False positive: the finding should NOT have been reported
            case = {
                "id": case_id,
                "language": language,
                "category": "negative_example",
                "severity": "none",
                "source": "feedback",
                "feedback_signal": "thumbs_down",
                "description": (
                    f"NEGATIVE EXAMPLE (user-reported false positive): {row.title}\n"
                    f"Original description: {row.description}"
                ),
                "snippet": f"# File: {row.file_path}\n# Lines: {row.line_start}-{row.line_end}\n# (content not captured at feedback time)",
                "expected_findings": [],
                "expected_no_findings": [
                    {
                        "category": category,
                        "note": row.note or f"User marked as false positive via thumbs_down on {row.feedback_at.date()}",
                    }
                ],
                "annotated_by": "user-feedback",
                "feedback_at": row.feedback_at.isoformat(),
                "original_finding_id": str(row.finding_id),
                "version": 1,
            }
        else:
            # Applied: confirmed true positive
            case = {
                "id": case_id,
                "language": language,
                "category": category,
                "severity": row.severity,
                "source": "feedback",
                "feedback_signal": "applied",
                "description": f"CONFIRMED TRUE POSITIVE (user applied the fix): {row.description}",
                "snippet": f"# File: {row.file_path}\n# Lines: {row.line_start}-{row.line_end}\n# (content not captured at feedback time)",
                "expected_findings": [
                    {
                        "category": category,
                        "severity": row.severity,
                        "file_path": "snippet",
                        "note": row.note or f"User confirmed by applying fix on {row.feedback_at.date()}",
                    }
                ],
                "expected_no_findings": [],
                "annotated_by": "user-feedback",
                "feedback_at": row.feedback_at.isoformat(),
                "original_finding_id": str(row.finding_id),
                "version": 1,
            }

        lang_dir = EVAL_DIR / language
        out_path = lang_dir / f"feedback_{str(row.id)[:8]}.yaml"

        if dry_run:
            print(f"  [DRY RUN] Would write: {out_path.relative_to(REPO_ROOT)}")
            exported += 1
            continue

        lang_dir.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            yaml.dump(case, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"  Exported: {out_path.relative_to(REPO_ROOT)} ({row.signal})")
        exported += 1

    return exported


async def main() -> int:
    parser = argparse.ArgumentParser(description="Export feedback signals as eval cases")
    parser.add_argument("--since", default="7d", help="Time window (e.g. 7d, 30d, 24h). Default: 7d")
    parser.add_argument(
        "--signal",
        choices=["thumbs_down", "applied"],
        help="Filter to a specific signal type. Default: both",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be exported without writing files")
    args = parser.parse_args()

    since = _parse_since(args.since)
    count = await export_feedback(since, args.signal, args.dry_run)

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Exported {count} eval case(s).")
    print("Run 'python scripts/eval.py' to measure precision/recall with the new cases.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
