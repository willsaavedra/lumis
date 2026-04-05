#!/usr/bin/env python3
"""
Cria na Stripe os produtos e preços dos planos Lumis (Starter, Growth, Scale),
mais o meter de uso para overage — alinhado a apps/api/billing/stripe_service.py e config.

Uso (na raiz do repo):
  export STRIPE_SECRET_KEY=sk_test_...
  python scripts/create_stripe_plans.py

Ou com chave em .env.local (STRIPE_SECRET_KEY=...).

Idempotente: reutiliza produtos/preços existentes (metadata lumis_plan / price_type).
Ao final imprime as variáveis para colar no .env.local.

Requisito: pip install 'stripe>=8.0.0'
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def _load_secret_key() -> str:
    api_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if api_key:
        return api_key
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.local")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("STRIPE_SECRET_KEY=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return ""


def _get_plan_configs() -> list[dict[str, Any]]:
    """Valores alinhados à página de pricing (USD/mês + overage por crédito)."""
    return [
        {
            "plan": "starter",
            "name": "Lumis Starter",
            "base_price_cents": 4900,
            "overage_unit_amount_cents": 35,
        },
        {
            "plan": "growth",
            "name": "Lumis Growth",
            "base_price_cents": 14900,
            "overage_unit_amount_cents": 25,
        },
        {
            "plan": "scale",
            "name": "Lumis Scale",
            "base_price_cents": 44900,
            "overage_unit_amount_cents": 15,
        },
    ]


def _find_or_create_meter(stripe: Any) -> str | None:
    """Meter usado em stripe_service.report_usage (event_name analysis_credit_consumed)."""
    try:
        meters = stripe.billing.Meter.list(limit=20)
        for m in meters.data:
            if getattr(m, "event_name", None) == "analysis_credit_consumed":
                return m.id
        meter = stripe.billing.Meter.create(
            display_name="Analysis Credits",
            event_name="analysis_credit_consumed",
            default_aggregation={"formula": "sum"},
            value_settings={"event_payload_key": "value"},
            customer_mapping={
                "event_payload_key": "stripe_customer_id",
                "type": "by_id",
            },
        )
        return meter.id
    except Exception as e:
        print(f"  ⚠ Meter: falhou ({e}). Overages podem precisar de configuração manual.")
        return None


def _find_or_create_product(stripe: Any, plan: str, name: str) -> Any:
    try:
        products = stripe.Product.search(query=f"metadata['lumis_plan']:'{plan}'")
        if products.data:
            return products.data[0]
    except Exception:
        pass
    return stripe.Product.create(
        name=name,
        metadata={"lumis_plan": plan, "lumis_product": "true"},
    )


def _find_price(prices: list, price_type: str) -> Any | None:
    for p in prices:
        meta = getattr(p, "metadata", None) or {}
        if meta.get("price_type") == price_type:
            return p
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria produtos e preços Stripe para os planos Lumis.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime só um JSON com ids (útil para CI).",
    )
    args = parser.parse_args()

    try:
        import stripe
    except ImportError:
        print("Instale: pip install 'stripe>=8.0.0'", file=sys.stderr)
        sys.exit(1)

    api_key = _load_secret_key()
    if not api_key.startswith("sk_"):
        print("Defina STRIPE_SECRET_KEY (sk_test_... ou sk_live_...) no ambiente ou em .env.local", file=sys.stderr)
        sys.exit(1)

    stripe.api_key = api_key
    if not args.json:
        print(f"Chave: {api_key[:12]}...")
        print()

    meter_id = _find_or_create_meter(stripe)
    if meter_id and not args.json:
        print(f"Meter: {meter_id}")
        print()

    plan_configs = _get_plan_configs()
    env_map: dict[str, str] = {}
    if meter_id:
        env_map["STRIPE_METER_ID"] = meter_id

    for cfg in plan_configs:
        plan = cfg["plan"]
        name = cfg["name"]
        base_cents = cfg["base_price_cents"]
        overage_cents = cfg["overage_unit_amount_cents"]

        if not args.json:
            print(f"— {name} ({plan})")

        product = _find_or_create_product(stripe, plan, name)
        if not args.json:
            print(f"  Produto: {product.id}")

        prices = stripe.Price.list(product=product.id, active=True, limit=20).data

        base_price = _find_price(prices, "base")
        if not base_price:
            base_price = stripe.Price.create(
                product=product.id,
                unit_amount=base_cents,
                currency="usd",
                recurring={"interval": "month"},
                metadata={"price_type": "base", "lumis_plan": plan},
            )
        if not args.json:
            print(f"  Preço base: {base_price.id} (${base_cents / 100:.0f}/mês)")

        overage_price = _find_price(prices, "overage")
        if not overage_price and meter_id:
            overage_price = stripe.Price.create(
                product=product.id,
                currency="usd",
                unit_amount=overage_cents,
                recurring={
                    "interval": "month",
                    "usage_type": "metered",
                    "meter": meter_id,
                },
                metadata={"price_type": "overage", "lumis_plan": plan},
            )
        elif not overage_price and not meter_id:
            if not args.json:
                print("  Overage: omitido (sem meter)")

        if overage_price and not args.json:
            print(f"  Preço overage: {overage_price.id} (${overage_cents / 100:.2f}/crédito)")

        u = plan.upper()
        env_map[f"STRIPE_PRICE_{u}_BASE"] = base_price.id
        if overage_price:
            env_map[f"STRIPE_PRICE_{u}_OVERAGE"] = overage_price.id

        if not args.json:
            print()

    if args.json:
        print(json.dumps(env_map, indent=2))
        return

    print("=" * 60)
    print("Cole no .env.local (ou variáveis de ambiente do deploy):")
    print()
    keys_order = ["STRIPE_METER_ID"]
    for p in ("STARTER", "GROWTH", "SCALE"):
        keys_order.append(f"STRIPE_PRICE_{p}_BASE")
        keys_order.append(f"STRIPE_PRICE_{p}_OVERAGE")
    printed = set()
    for k in keys_order:
        if k in env_map:
            print(f"{k}={env_map[k]}")
            printed.add(k)
    for k in sorted(env_map.keys()):
        if k not in printed:
            print(f"{k}={env_map[k]}")
    print()
    print("Reinicie API/worker após atualizar.")


if __name__ == "__main__":
    main()
