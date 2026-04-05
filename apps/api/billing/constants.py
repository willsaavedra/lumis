"""Shared billing constants (overage USD per credit by plan)."""
from __future__ import annotations

# Align with apps/api/routers/billing.py OVERAGE_RATES — free uses starter-equivalent rate
OVERAGE_RATES_USD_PER_CREDIT: dict[str, float] = {
    "free": 0.35,
    "starter": 0.35,
    "growth": 0.25,
    "scale": 0.15,
    "enterprise": 0.15,
}


def overage_rate_for_plan(plan: str | None) -> float:
    p = (plan or "free").strip().lower()
    return OVERAGE_RATES_USD_PER_CREDIT.get(p, 0.35)
