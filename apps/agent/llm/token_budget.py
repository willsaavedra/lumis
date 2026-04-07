"""Token-aware batch construction for LLM analysis.

Groups files into batches that fit the context window of the target model,
sorted by semantic domain for cohesion, and flags oversized files for chunking.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Model context budgets
# ---------------------------------------------------------------------------

CONTEXT_BUDGETS: dict[str, dict[str, int | float]] = {
    "claude-sonnet-4-20250514": {
        "context_window": 200_000,
        "fixed_overhead": 12_000,
        "output_reserved": 6_000,
        "safety_margin": 0.20,
    },
    "claude-haiku-4-5-20251001": {
        "context_window": 200_000,
        "fixed_overhead": 10_000,
        "output_reserved": 4_000,
        "safety_margin": 0.20,
    },
}

_DEFAULT_BUDGET = {
    "context_window": 32_000,
    "fixed_overhead": 8_000,
    "output_reserved": 3_000,
    "safety_margin": 0.20,
}

# Soft limit: beyond this many content tokens the model's attention degrades
SOFT_QUALITY_LIMIT = 60_000

# ---------------------------------------------------------------------------
# Domain priority for batch cohesion (Phase 2)
# ---------------------------------------------------------------------------

DOMAIN_KEYWORDS: list[str] = [
    "payment", "order", "checkout", "transaction", "invoice",
    "inventory", "stock", "warehouse",
    "auth", "authentication", "authorization", "session", "token",
    "billing", "subscription", "pricing",
    "cart", "discount", "coupon",
    "notification", "email", "sms",
    "user", "account", "profile",
]

_INFRA_KEYWORDS = ("middleware", "interceptor", "filter", "guard", "server", "router", "routes")


def _classify_domain(file_path: str) -> tuple[int, str]:
    """Return (priority_rank, domain_name) for sorting files by business domain."""
    lower = file_path.lower()
    for i, keyword in enumerate(DOMAIN_KEYWORDS):
        if keyword in lower:
            return (i, keyword)
    for kw in _INFRA_KEYWORDS:
        if kw in lower:
            return (len(DOMAIN_KEYWORDS), "infra")
    return (len(DOMAIN_KEYWORDS) + 1, "other")


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Fast heuristic: ~4 chars per token (no tiktoken dependency)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Budget calculation
# ---------------------------------------------------------------------------

def _get_budget(model: str) -> dict:
    return CONTEXT_BUDGETS.get(model, _DEFAULT_BUDGET)


def usable_file_budget(model: str, call_graph_tokens: int = 0) -> int:
    """Max tokens available for file content in a single batch."""
    b = _get_budget(model)
    raw = b["context_window"] - b["fixed_overhead"] - b["output_reserved"] - call_graph_tokens
    capped = min(raw, SOFT_QUALITY_LIMIT) if raw > SOFT_QUALITY_LIMIT else raw
    return int(capped * (1.0 - b["safety_margin"]))


# ---------------------------------------------------------------------------
# Batch result types
# ---------------------------------------------------------------------------

@dataclass
class BatchPlan:
    """Result of compute_batches: batches of normal files + oversized files."""
    batches: list[list[dict]] = field(default_factory=list)
    oversized_files: list[dict] = field(default_factory=list)
    budget_per_batch: int = 0


# ---------------------------------------------------------------------------
# Batch construction
# ---------------------------------------------------------------------------

def compute_batches(
    files: list[dict],
    model: str,
    call_graph_tokens: int = 0,
) -> BatchPlan:
    """
    Group files into batches that respect the model's context window.

    - Files are sorted by domain priority for semantic cohesion.
    - Files whose token count exceeds the per-batch budget are separated
      into `oversized_files` for chunking (handled by file_chunker).
    - Never truncates file content.

    Each file dict must have 'path' and 'content' keys.
    """
    budget = usable_file_budget(model, call_graph_tokens)
    if budget <= 0:
        budget = 10_000

    sorted_files = sorted(files, key=lambda f: _classify_domain(f.get("path", "")))

    plan = BatchPlan(budget_per_batch=budget)
    current_batch: list[dict] = []
    current_tokens = 0

    for f in sorted_files:
        content = f.get("content") or ""
        file_tokens = estimate_tokens(content)

        if file_tokens > budget:
            plan.oversized_files.append(f)
            continue

        if current_tokens + file_tokens > budget and current_batch:
            plan.batches.append(current_batch)
            current_batch = [f]
            current_tokens = file_tokens
        else:
            current_batch.append(f)
            current_tokens += file_tokens

    if current_batch:
        plan.batches.append(current_batch)

    log.info(
        "batch_plan_computed",
        total_files=len(files),
        batches=len(plan.batches),
        oversized=len(plan.oversized_files),
        budget_per_batch=budget,
        model=model,
    )
    return plan
