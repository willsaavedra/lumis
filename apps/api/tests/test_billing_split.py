"""Reservation split: plan credits vs USD wallet."""
from decimal import Decimal

from apps.api.billing.billing_gate import _compute_reservation_split


def test_split_uses_plan_first_then_wallet_at_rate() -> None:
    """10 credits remaining, job cost 15, starter rate 0.35 → 5 credits from wallet = $1.75."""
    plan_used, usd, from_wallet = _compute_reservation_split(
        cost=15,
        credits_remaining=10,
        extra_balance_usd=Decimal("10.00"),
        plan="starter",
    )
    assert plan_used == 10
    assert from_wallet == 5
    assert usd == Decimal("1.75")


def test_split_all_from_plan() -> None:
    plan_used, usd, from_wallet = _compute_reservation_split(
        cost=3,
        credits_remaining=100,
        extra_balance_usd=Decimal("0"),
        plan="growth",
    )
    assert plan_used == 3
    assert from_wallet == 0
    assert usd == Decimal("0.00")
