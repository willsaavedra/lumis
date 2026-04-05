#!/usr/bin/env python3
"""
Calibrate score penalties from user feedback.

Reads finding_feedback rows where:
  - target_type = 'finding' AND signal = 'thumbs_down'  → false positives
  - target_type = 'finding' AND signal = 'thumbs_up'    → true positives

For each (pillar, severity) combination, computes the false-positive rate.
When FPR is high, it reduces the penalty for that category so noisy signals
don't unfairly penalize the score.

Outputs score_config.json that score.py loads at startup.

Usage:
    python scripts/calibrate_scores.py [--output score_config.json] [--min-samples 5]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

DEFAULT_PENALTIES = {
    "dimension": {"critical": 20, "warning": 10, "info": 3},
    "pillar":    {"critical": 25, "warning": 12, "info": 5},
}

# Minimum samples before we adjust a penalty
MIN_SAMPLES = 5
# If FPR exceeds this threshold, we reduce the penalty
FP_THRESHOLD = 0.30


async def load_feedback() -> list[dict]:
    """Load all finding-level feedback joined with findings from the DB."""
    from sqlalchemy import select, text
    from apps.api.core.database import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        result = await session.execute(text("""
            SELECT
                ff.signal,
                f.pillar,
                f.severity,
                f.dimension
            FROM finding_feedback ff
            JOIN findings f ON f.id = ff.finding_id
            WHERE ff.target_type = 'finding'
        """))
        return [dict(row._mapping) for row in result]


def compute_penalties(rows: list[dict], min_samples: int) -> dict:
    """
    For each (pillar, severity), count TP (thumbs_up) and FP (thumbs_down).
    If FPR >= FP_THRESHOLD and samples >= min_samples, reduce penalty.
    """
    counts: dict[tuple, dict] = defaultdict(lambda: {"tp": 0, "fp": 0})

    for row in rows:
        key = (row["pillar"], row["severity"])
        if row["signal"] == "thumbs_up":
            counts[key]["tp"] += 1
        elif row["signal"] == "thumbs_down":
            counts[key]["fp"] += 1

    pillar_penalties: dict[str, dict] = {}

    for (pillar, severity), c in counts.items():
        total = c["tp"] + c["fp"]
        if total < min_samples:
            continue
        fpr = c["fp"] / total
        default_penalty = DEFAULT_PENALTIES["pillar"].get(severity, 5)

        if fpr >= FP_THRESHOLD:
            # Reduce penalty proportionally: at 100% FPR → 0 penalty
            adjusted = int(default_penalty * (1.0 - fpr))
            adjusted = max(0, adjusted)
            if pillar not in pillar_penalties:
                pillar_penalties[pillar] = {}
            pillar_penalties[pillar][severity] = adjusted
            print(
                f"  [{pillar}/{severity}] FPR={fpr:.0%} ({c['fp']}/{total}) "
                f"→ penalty {default_penalty} → {adjusted}"
            )
        else:
            print(
                f"  [{pillar}/{severity}] FPR={fpr:.0%} ({c['fp']}/{total}) "
                f"→ no change (penalty stays {default_penalty})"
            )

    return pillar_penalties


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate Lumis score penalties from feedback")
    parser.add_argument("--output", default="score_config.json", help="Output JSON file path")
    parser.add_argument("--min-samples", type=int, default=MIN_SAMPLES, help="Minimum feedback samples to adjust")
    parser.add_argument("--dry-run", action="store_true", help="Print config without writing file")
    args = parser.parse_args()

    print("Loading feedback from database...")
    rows = asyncio.run(load_feedback())
    print(f"Found {len(rows)} feedback rows.")

    if not rows:
        print("No feedback found — nothing to calibrate.")
        return

    print("\nComputing calibrated penalties:")
    pillar_penalties = compute_penalties(rows, args.min_samples)

    config = {
        "dimension_penalties": DEFAULT_PENALTIES["dimension"],
        "pillar_penalties": pillar_penalties,
        "_meta": {
            "samples": len(rows),
            "min_samples": args.min_samples,
            "fp_threshold": FP_THRESHOLD,
        }
    }

    print(f"\nCalibrated config:\n{json.dumps(config, indent=2)}")

    if not args.dry_run:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(config, indent=2))
        print(f"\nWrote {output_path}")
        print("Restart the worker to apply the new penalties (score.py reads at startup).")
    else:
        print("\n[dry-run] No file written.")


if __name__ == "__main__":
    main()
