"""Parallel batch executor with rate limiting, retry, and batch splitting.

Runs LLM analysis batches concurrently via asyncio.Semaphore, with automatic
retry and batch-split-on-failure strategy.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

import structlog

log = structlog.get_logger(__name__)


@dataclass
class BatchResult:
    batch_index: int
    files: list[dict]
    findings: list[dict] = field(default_factory=list)
    error: str | None = None
    tokens_used: int = 0
    retries: int = 0


AnalyzeFn = Callable[[list[dict]], Awaitable[list[dict]]]
OnCompleteFn = Callable[[BatchResult], Awaitable[None]]


class BatchRunner:
    """Execute LLM batches in parallel with semaphore-based concurrency control."""

    def __init__(
        self,
        max_concurrent: int = 4,
        max_retries: int = 3,
        base_backoff: float = 2.0,
    ):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_retries = max_retries
        self._base_backoff = base_backoff

    async def run_all(
        self,
        batches: list[list[dict]],
        analyze_fn: AnalyzeFn,
        on_complete: OnCompleteFn | None = None,
    ) -> list[BatchResult]:
        """
        Execute all batches concurrently (up to max_concurrent).

        analyze_fn: async function that takes a list of file dicts and returns findings.
        on_complete: optional async callback fired after each batch completes.

        Returns a BatchResult for every batch (including failed ones).
        """
        tasks = [
            self._run_one(i, batch, analyze_fn, on_complete)
            for i, batch in enumerate(batches)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: list[BatchResult] = []
        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                final.append(BatchResult(
                    batch_index=i,
                    files=batches[i],
                    error=str(r),
                ))
            elif isinstance(r, list):
                final.extend(r)
            else:
                final.append(r)
        return final

    async def _run_one(
        self,
        idx: int,
        batch: list[dict],
        analyze_fn: AnalyzeFn,
        on_complete: OnCompleteFn | None,
    ) -> BatchResult | list[BatchResult]:
        async with self._semaphore:
            return await self._run_with_retry(idx, batch, analyze_fn, on_complete)

    async def _run_with_retry(
        self,
        idx: int,
        batch: list[dict],
        analyze_fn: AnalyzeFn,
        on_complete: OnCompleteFn | None,
        attempt: int = 0,
    ) -> BatchResult | list[BatchResult]:
        try:
            findings = await analyze_fn(batch)
            result = BatchResult(
                batch_index=idx,
                files=batch,
                findings=findings,
                retries=attempt,
            )
            if on_complete:
                await on_complete(result)
            return result

        except Exception as e:
            log.warning(
                "batch_failed",
                batch_index=idx,
                attempt=attempt + 1,
                max_retries=self._max_retries,
                files_in_batch=len(batch),
                error=str(e),
            )

            if attempt < self._max_retries - 1:
                wait = self._base_backoff ** (attempt + 1)
                await asyncio.sleep(wait)
                return await self._run_with_retry(idx, batch, analyze_fn, on_complete, attempt + 1)

            # Max retries exhausted — try splitting the batch
            if len(batch) > 1:
                log.info(
                    "batch_splitting",
                    batch_index=idx,
                    original_size=len(batch),
                )
                mid = len(batch) // 2
                left = await self._run_with_retry(idx, batch[:mid], analyze_fn, on_complete, 0)
                right = await self._run_with_retry(idx, batch[mid:], analyze_fn, on_complete, 0)

                results = []
                for r in (left, right):
                    if isinstance(r, list):
                        results.extend(r)
                    else:
                        results.append(r)
                return results

            # Single-file batch that still fails
            result = BatchResult(
                batch_index=idx,
                files=batch,
                error=str(e),
                retries=attempt + 1,
            )
            if on_complete:
                await on_complete(result)
            return result
