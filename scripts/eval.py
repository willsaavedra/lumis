#!/usr/bin/env python3
"""
Lumis Agent Evaluation Script
==============================
Evaluates agent finding quality against annotated YAML test cases.

Metrics computed:
  - Precision = TP / (TP + FP)
  - Recall    = TP / (TP + FN)
  - FPR       = FP / (FP + TN)
  - F1        = 2 * Precision * Recall / (Precision + Recall)

Usage:
    python scripts/eval.py                         # all cases
    python scripts/eval.py --language go           # filter by language
    python scripts/eval.py --category handler_no_span
    python scripts/eval.py --baseline results/baseline.json --compare results/current.json

Output:
    Prints a table to stdout and writes results/eval_<timestamp>.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Path setup — allow running from repo root without install
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

EVAL_DIR = REPO_ROOT / "eval" / "cases"
RESULTS_DIR = REPO_ROOT / "results"


# ---------------------------------------------------------------------------
# Case loading
# ---------------------------------------------------------------------------

def load_cases(
    language: str | None = None,
    category: str | None = None,
) -> list[dict]:
    cases = []
    for path in sorted(EVAL_DIR.rglob("*.yaml")):
        with open(path) as f:
            case = yaml.safe_load(f)
        if not case:
            continue
        if language and case.get("language") != language:
            continue
        if category and case.get("category") != category:
            continue
        case["_source"] = str(path.relative_to(REPO_ROOT))
        cases.append(case)
    return cases


# ---------------------------------------------------------------------------
# Agent invocation (lightweight — calls the nodes directly, not Celery)
# ---------------------------------------------------------------------------

async def _run_agent_on_snippet(case: dict) -> list[dict]:
    """
    Run a minimal agent pipeline on the snippet from a test case.
    Uses analyze_coverage + analyze_efficiency nodes directly to avoid
    the need for a full DB, Git clone, or Celery worker.
    """
    from apps.agent.nodes.analyze_coverage import analyze_coverage_node
    from apps.agent.nodes.analyze_efficiency import analyze_efficiency_node

    snippet = case.get("snippet", "")
    language = case.get("language", "")
    ext_map = {
        "go": ".go", "python": ".py", "javascript": ".js",
        "typescript": ".ts", "java": ".java", "terraform": ".tf",
    }
    ext = ext_map.get(language, ".txt")
    fake_path = f"eval_snippet{ext}"

    fake_state: dict[str, Any] = {
        "job_id": f"eval-{case['id']}",
        "tenant_id": "eval-tenant",
        "request": {
            "analysis_type": "full",
            "job_id": f"eval-{case['id']}",
            "tenant_id": "eval-tenant",
        },
        "changed_files": [
            {
                "path": fake_path,
                "language": language,
                "content": snippet,
                "relevance_score": 2,
            }
        ],
        "findings": [],
        "call_graph": {},
        "coverage_map": {},
        "dd_coverage": None,
        "repo_context": {},
        "token_usage": {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0, "cost_usd": 0.0},
        "messages": [],
        "error": None,
        "stage": "eval",
        "progress_pct": 0,
    }

    # Run coverage analysis
    coverage_result = await analyze_coverage_node(fake_state)
    fake_state["findings"] = coverage_result.get("findings", [])

    # Run efficiency analysis (static only — no LLM cost)
    if language in ("go", "python", "javascript", "typescript"):
        eff_result = await analyze_efficiency_node(fake_state)
        fake_state["findings"] = eff_result.get("findings", [])

    return fake_state["findings"]


# ---------------------------------------------------------------------------
# Matching: compare agent findings to expected/expected_no findings
# ---------------------------------------------------------------------------

_CATEGORY_ALIASES: dict[str, list[str]] = {
    "handler_no_span":        ["No span on HTTP/gRPC handler", "handler", "handler_no_span"],
    "error_path_missing_span": ["Error path without span", "error_path", "blind error"],
    "unstructured_log":       ["Unstructured log", "unstructured"],
    "high_cardinality_label": ["High cardinality", "cardinality"],
    "pii_in_logs":            ["PII", "pii", "Potential PII"],
    "iac_missing_alarm":      ["SQS queue without", "CloudWatch alarm", "alarm"],
    "iac_lambda_no_layer":    ["Lambda function without", "observability layer"],
    "iac_missing_tags":       ["missing standard observability tags", "env/service/team"],
}


def _finding_matches_category(finding: dict, category: str) -> bool:
    """Return True if a finding matches the expected category (fuzzy via aliases)."""
    aliases = _CATEGORY_ALIASES.get(category, [category])
    title = (finding.get("title") or "").lower()
    desc = (finding.get("description") or "").lower()
    for alias in aliases:
        if alias.lower() in title or alias.lower() in desc:
            return True
    return False


def evaluate_case(case: dict, agent_findings: list[dict]) -> dict:
    """
    Evaluate one test case.
    Returns a dict with: tp, fp, fn, tn, details.
    """
    expected = case.get("expected_findings", [])
    expected_no = case.get("expected_no_findings", [])

    tp = fp = fn = 0
    details: list[dict] = []

    # True positives and false negatives
    for exp in expected:
        cat = exp.get("category", "")
        matched = any(_finding_matches_category(f, cat) for f in agent_findings)
        if matched:
            tp += 1
            details.append({"type": "TP", "category": cat})
        else:
            fn += 1
            details.append({"type": "FN", "category": cat, "note": "Expected but not found"})

    # False positives
    for finding in agent_findings:
        matched_expected = any(
            _finding_matches_category(finding, exp.get("category", ""))
            for exp in expected
        )
        if not matched_expected:
            # Check if it matches something in expected_no
            in_no_list = any(
                _finding_matches_category(finding, no.get("category", ""))
                for no in expected_no
            )
            if in_no_list:
                fp += 1
                details.append({
                    "type": "FP",
                    "finding_title": finding.get("title"),
                    "note": "Should NOT have been reported",
                })

    # True negatives
    for no_exp in expected_no:
        cat = no_exp.get("category", "")
        wrongly_found = any(_finding_matches_category(f, cat) for f in agent_findings)
        if not wrongly_found:
            # TN: correctly not reported
            pass

    tn = len(expected_no) - fp

    return {
        "case_id": case["id"],
        "source": case.get("_source"),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": max(tn, 0),
        "details": details,
    }


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------

def compute_metrics(results: list[dict]) -> dict:
    tp = sum(r["tp"] for r in results)
    fp = sum(r["fp"] for r in results)
    fn = sum(r["fn"] for r in results)
    tn = sum(r["tn"] for r in results)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    fpr       = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "fpr": round(fpr, 4),
        "f1": round(f1, 4),
    }


# ---------------------------------------------------------------------------
# Baseline comparison
# ---------------------------------------------------------------------------

def compare_to_baseline(current: dict, baseline: dict) -> list[str]:
    """Return a list of regression warnings."""
    warnings = []
    prec_drop = baseline["precision"] - current["precision"]
    fpr_rise  = current["fpr"] - baseline["fpr"]

    if prec_drop > 0.05:
        warnings.append(
            f"REGRESSION: Precision dropped {prec_drop:.1%} "
            f"({baseline['precision']:.2%} → {current['precision']:.2%})"
        )
    if fpr_rise > 0.03:
        warnings.append(
            f"REGRESSION: FPR rose {fpr_rise:.1%} "
            f"({baseline['fpr']:.2%} → {current['fpr']:.2%})"
        )
    return warnings


# ---------------------------------------------------------------------------
# Pretty-print table
# ---------------------------------------------------------------------------

def print_table(metrics: dict, case_results: list[dict], elapsed: float) -> None:
    print("\n" + "=" * 70)
    print("  Lumis Agent — Evaluation Results")
    print("=" * 70)
    print(f"  Cases: {len(case_results)}   Elapsed: {elapsed:.1f}s")
    print("-" * 70)
    print(f"  {'Metric':<20} {'Value':>10}")
    print("-" * 70)
    for k, v in metrics.items():
        if isinstance(v, float):
            print(f"  {k:<20} {v:>10.2%}")
        else:
            print(f"  {k:<20} {v:>10}")
    print("-" * 70)

    if any(r["fp"] > 0 or r["fn"] > 0 for r in case_results):
        print("\n  Failures:")
        for r in case_results:
            for d in r["details"]:
                if d["type"] in ("FP", "FN"):
                    print(f"  [{d['type']}] {r['case_id']} — {d.get('category') or d.get('finding_title')}")
    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main() -> int:
    parser = argparse.ArgumentParser(description="Lumis agent evaluation")
    parser.add_argument("--language", help="Filter by language (go, python, javascript, ...)")
    parser.add_argument("--category", help="Filter by finding category")
    parser.add_argument("--baseline", help="Path to baseline JSON for regression comparison")
    parser.add_argument("--compare", help="Path to results JSON to compare against baseline")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM calls (static heuristics only). Faster and free.")
    args = parser.parse_args()

    if args.compare and args.baseline:
        with open(args.baseline) as f:
            baseline = json.load(f)
        with open(args.compare) as f:
            current = json.load(f)
        warnings = compare_to_baseline(current["metrics"], baseline["metrics"])
        if warnings:
            for w in warnings:
                print(f"  ⚠  {w}")
            return 1
        print("  ✓  No regressions detected.")
        return 0

    cases = load_cases(language=args.language, category=args.category)
    if not cases:
        print(f"No eval cases found in {EVAL_DIR}")
        return 1

    print(f"Running eval on {len(cases)} cases...")
    t0 = time.monotonic()
    case_results: list[dict] = []

    for case in cases:
        try:
            if args.no_llm:
                # Static-only: run efficiency node without LLM
                from apps.agent.nodes.analyze_efficiency import analyze_efficiency_node
                language = case.get("language", "")
                ext_map = {"go": ".go", "python": ".py", "javascript": ".js", "typescript": ".ts"}
                ext = ext_map.get(language, ".txt")
                fake_state: dict[str, Any] = {
                    "job_id": f"eval-{case['id']}",
                    "tenant_id": "eval-tenant",
                    "request": {"analysis_type": "full"},
                    "changed_files": [{
                        "path": f"snippet{ext}",
                        "language": language,
                        "content": case.get("snippet", ""),
                        "relevance_score": 2,
                    }],
                    "findings": [],
                }
                result = await analyze_efficiency_node(fake_state)
                agent_findings = result.get("findings", [])
            else:
                agent_findings = await _run_agent_on_snippet(case)
        except Exception as exc:
            print(f"  ERROR running case {case.get('id')}: {exc}")
            agent_findings = []

        result = evaluate_case(case, agent_findings)
        case_results.append(result)

    elapsed = time.monotonic() - t0
    metrics = compute_metrics(case_results)
    print_table(metrics, case_results, elapsed)

    # Save results
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"eval_{ts}.json"
    with open(out_path, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "case_results": case_results,
        }, f, indent=2)
    print(f"  Results saved to {out_path.relative_to(REPO_ROOT)}")

    if args.baseline:
        with open(args.baseline) as f:
            baseline = json.load(f)
        warnings = compare_to_baseline(metrics, baseline["metrics"])
        if warnings:
            for w in warnings:
                print(f"  ⚠  {w}")
            return 1

    # Exit 1 if F1 < 0.5 (minimum acceptable quality)
    return 0 if metrics["f1"] >= 0.5 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
