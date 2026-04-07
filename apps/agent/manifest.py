"""Analysis manifest — tracks every file's status from triage to final report.

Guarantees the invariant: no file silently disappears between pre_triage and
the execution summary. Every eligible file is either analyzed or explicitly
marked as failed with a reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import structlog

log = structlog.get_logger(__name__)

FileStatusValue = Literal[
    "pending",
    "in_batch",
    "analyzing",
    "completed",
    "failed",
    "skipped_triage",
]


@dataclass
class FileStatus:
    path: str
    triage_score: int
    status: FileStatusValue = "pending"
    batch_index: int | None = None
    chunk_count: int = 1
    findings_count: int = 0
    tokens_used: int = 0
    error: str | None = None
    completed_at: datetime | None = None


class CoverageGuaranteeViolation(Exception):
    """Raised when eligible files were not analyzed and not explicitly failed."""


class AnalysisManifest:
    """
    Tracks the analysis status of every file in scope.

    Created from the filtered file list in analyze_coverage_node.
    Updated by batch callbacks as each batch completes.
    Asserted before generating the final report.
    """

    def __init__(self, files: list[dict]):
        self._files: dict[str, FileStatus] = {}
        self.total_batches: int = 0
        self.retry_count: int = 0

        for f in files:
            path = f.get("path", "")
            score = f.get("relevance_score", 0)
            status: FileStatusValue = "pending" if score >= 1 else "skipped_triage"
            self._files[path] = FileStatus(path=path, triage_score=score, status=status)

    # -- Mutation methods ---------------------------------------------------

    def mark_batched(self, path: str, batch_idx: int) -> None:
        fs = self._files.get(path)
        if fs:
            fs.status = "in_batch"
            fs.batch_index = batch_idx

    def mark_analyzing(self, path: str) -> None:
        fs = self._files.get(path)
        if fs:
            fs.status = "analyzing"

    def mark_completed(self, path: str, findings_count: int = 0, tokens_used: int = 0) -> None:
        fs = self._files.get(path)
        if fs:
            fs.status = "completed"
            fs.findings_count = findings_count
            fs.tokens_used = tokens_used
            fs.completed_at = datetime.now(timezone.utc)

    def mark_failed(self, path: str, error: str = "") -> None:
        fs = self._files.get(path)
        if fs:
            fs.status = "failed"
            fs.error = error

    def mark_chunked(self, path: str, chunk_count: int) -> None:
        fs = self._files.get(path)
        if fs:
            fs.chunk_count = chunk_count

    def record_retry(self) -> None:
        self.retry_count += 1

    # -- Query methods ------------------------------------------------------

    @property
    def eligible(self) -> list[FileStatus]:
        return [f for f in self._files.values() if f.triage_score >= 1]

    @property
    def completed_count(self) -> int:
        return sum(1 for f in self.eligible if f.status == "completed")

    @property
    def eligible_count(self) -> int:
        return len(self.eligible)

    @property
    def failed_files(self) -> list[FileStatus]:
        return [f for f in self.eligible if f.status == "failed"]

    @property
    def coverage_pct(self) -> float:
        elig = self.eligible
        if not elig:
            return 100.0
        completed = sum(1 for f in elig if f.status == "completed")
        return completed / len(elig) * 100.0

    @property
    def is_complete(self) -> bool:
        return all(f.status in ("completed", "failed") for f in self.eligible)

    # -- Guarantee assertion ------------------------------------------------

    def assert_complete(self) -> None:
        """
        Verify no eligible file was silently skipped.
        Call before generating the final report.
        """
        silently_skipped = [
            f for f in self.eligible
            if f.status not in ("completed", "failed")
        ]
        if silently_skipped:
            paths = [f.path for f in silently_skipped]
            log.error(
                "coverage_guarantee_violation",
                skipped_count=len(paths),
                paths=paths[:20],
            )
            for f in silently_skipped:
                f.status = "failed"
                f.error = "silently_skipped_by_engine"

    # -- Serialization for execution summary --------------------------------

    def to_completeness_report(self) -> dict:
        elig = self.eligible
        completed = [f for f in elig if f.status == "completed"]
        failed = [f for f in elig if f.status == "failed"]
        chunked = [f for f in elig if f.chunk_count > 1]
        skipped = [f for f in self._files.values() if f.status == "skipped_triage"]

        return {
            "total_files_in_scope": len(self._files),
            "files_eligible": len(elig),
            "files_analyzed": len(completed),
            "files_skipped_by_triage": len(skipped),
            "files_failed": len(failed),
            "files_chunked": len(chunked),
            "coverage_pct": round(self.coverage_pct, 1),
            "is_complete": len(failed) == 0 and self.is_complete,
            "batches_executed": self.total_batches,
            "batches_retried": self.retry_count,
            "total_tokens_used": sum(f.tokens_used for f in elig),
            "analyzed_files": [f.path for f in completed],
            "failed_files": [
                {"path": f.path, "reason": f.error or "unknown"}
                for f in failed
            ],
        }
