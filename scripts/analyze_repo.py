"""
CLI tool for manually triggering repository analysis.
Usage: python scripts/analyze_repo.py --repo https://github.com/owner/repo
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path


async def analyze(repo_url: str, ref: str = "main", analysis_type: str = "full") -> None:
    sys.path.insert(0, "/workspace")

    print(f"Lumis — Analyzing {repo_url}@{ref}")
    print("=" * 60)

    # Create a minimal job state for direct agent execution
    job_id = str(uuid.uuid4())

    from apps.agent.schemas import AgentState
    from apps.agent.graph import analysis_graph

    initial_state: AgentState = {
        "job_id": job_id,
        "tenant_id": "cli-tenant",
        "request": {
            "job_id": job_id,
            "tenant_id": "cli-tenant",
            "repo_id": "cli-repo",
            "repo_full_name": repo_url.replace("https://github.com/", ""),
            "clone_url": repo_url if not repo_url.endswith(".git") else repo_url,
            "ref": ref,
            "pr_number": None,
            "commit_sha": None,
            "changed_files": [],
            "analysis_type": analysis_type,
            "installation_id": None,
            "scm_type": "github",
        },
        "repo_path": None,
        "changed_files": [],
        "call_graph": None,
        "coverage_map": None,
        "dd_coverage": None,
        "findings": [],
        "efficiency_scores": {},
        "token_usage": {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0, "cost_usd": 0.0},
        "messages": [],
        "error": None,
        "stage": "starting",
        "progress_pct": 0,
    }

    print(f"Job ID: {job_id}")
    print(f"Type: {analysis_type}")
    print()

    try:
        final_state = await analysis_graph.ainvoke(initial_state)
    except Exception as e:
        print(f"Analysis failed: {e}")
        sys.exit(1)

    # Print results
    scores = final_state.get("efficiency_scores", {})
    findings = final_state.get("findings", [])

    print("\n── SCORES ──────────────────────────────────────────────")
    print(f"  Global:  {scores.get('global_score', 'N/A')}/100")
    print(f"  Metrics: {scores.get('metrics', 'N/A')}/100")
    print(f"  Logs:    {scores.get('logs', 'N/A')}/100")
    print(f"  Traces:  {scores.get('traces', 'N/A')}/100")

    print(f"\n── FINDINGS ({len(findings)}) ────────────────────────────────")
    by_severity = {"critical": [], "warning": [], "info": []}
    for f in findings:
        by_severity.get(f.get("severity", "info"), []).append(f)

    for severity in ("critical", "warning", "info"):
        for f in by_severity[severity]:
            icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(severity, "⚪")
            print(f"\n{icon} [{severity.upper()}] {f.get('title', '')}")
            if f.get("file_path"):
                print(f"   File: {f['file_path']}:{f.get('line_start', '?')}")
            print(f"   {f.get('description', '')}")
            if f.get("estimated_monthly_cost_impact", 0) > 0:
                print(f"   Cost impact: ~${f['estimated_monthly_cost_impact']:.0f}/month")
            if f.get("suggestion"):
                print(f"   Fix:")
                for line in f["suggestion"].split("\n"):
                    print(f"     {line}")

    total_cost = sum(f.get("estimated_monthly_cost_impact", 0) for f in findings)
    if total_cost > 0:
        print(f"\n⚠️  Total estimated cost impact: ~${total_cost:.0f}/month")

    print("\n✓ Analysis complete")


def main() -> None:
    parser = argparse.ArgumentParser(description="Lumis — Repository observability analysis")
    parser.add_argument("--repo", required=True, help="Repository URL or owner/name")
    parser.add_argument("--ref", default="main", help="Branch, tag, or commit SHA")
    parser.add_argument("--type", dest="analysis_type", default="full",
                        choices=["quick", "full", "repository"], help="Analysis depth")
    args = parser.parse_args()

    repo_url = args.repo
    if not repo_url.startswith("https://"):
        repo_url = f"https://github.com/{repo_url}"

    asyncio.run(analyze(repo_url, args.ref, args.analysis_type))


if __name__ == "__main__":
    main()
