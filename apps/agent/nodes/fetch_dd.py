"""Node 4: Fetch existing Datadog coverage."""
from __future__ import annotations

import structlog

from apps.agent.nodes.base import publish_progress, publish_thought
from apps.agent.schemas import AgentState

log = structlog.get_logger(__name__)


async def fetch_dd_coverage_node(state: AgentState) -> dict:
    """
    Fetch existing Datadog coverage for the service.
    Gracefully degrades if DD is not configured.
    """
    await publish_progress(state, "fetching_dd", 40, "Checking Datadog coverage...", stage_index=4)

    from apps.agent.core.config import settings
    if not settings.dd_api_key or not settings.dd_app_key:
        log.info("datadog_not_configured_skipping")
        await publish_thought(state, "fetch_dd", "Datadog not configured — skipping coverage check", status="done")
        await publish_progress(state, "fetching_dd", 45, "Datadog not configured — skipping.", stage_index=4)
        return {"dd_coverage": None}

    repo_full_name = state["request"]["repo_full_name"]
    service_name = repo_full_name.split("/")[-1] if "/" in repo_full_name else repo_full_name

    try:
        import httpx
        headers = {
            "DD-API-KEY": settings.dd_api_key,
            "DD-APPLICATION-KEY": settings.dd_app_key,
        }
        base_url = f"https://api.{settings.dd_site}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Fetch metrics for service
            metrics_resp = await client.get(
                f"{base_url}/api/v1/metrics",
                headers=headers,
                params={"q": f"service:{service_name}"},
            )
            metrics = metrics_resp.json().get("metrics", []) if metrics_resp.status_code == 200 else []

            # Fetch APM services
            services_resp = await client.get(
                f"{base_url}/api/v2/apm/rum/analytics/aggregate",
                headers=headers,
            )
            apm_services = []

        dd_coverage = {
            "metrics": metrics[:50],
            "monitors": [],
            "apm_services": apm_services,
            "dashboards": [],
        }
        log.info("dd_coverage_fetched", service=service_name, metrics_count=len(metrics))
        await publish_progress(state, "fetching_dd", 45, f"Found {len(metrics)} existing metrics.")
        return {"dd_coverage": dd_coverage}

    except Exception as e:
        log.warning("dd_fetch_failed_continuing", error=str(e))
        await publish_progress(state, "fetching_dd", 45, "Datadog fetch failed — continuing without coverage data.")
        return {"dd_coverage": None}
