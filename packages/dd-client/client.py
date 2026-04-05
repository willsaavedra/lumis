"""
Datadog API client for fetching existing monitoring coverage.
Used by the agent to understand what's already instrumented in production.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx
import structlog

log = structlog.get_logger(__name__)

DD_API_BASE = "https://api.{site}"


@dataclass
class DatadogCoverage:
    service_name: str
    metrics: list[str] = field(default_factory=list)
    monitors: list[dict] = field(default_factory=list)
    apm_services: list[str] = field(default_factory=list)
    dashboards: list[str] = field(default_factory=list)
    has_apm: bool = False


class DatadogClient:
    """
    Client for Datadog API v1/v2.
    Fetches existing metrics, monitors, and APM services for a given service.
    """

    def __init__(self, api_key: str, app_key: str, site: str = "datadoghq.com") -> None:
        self.api_key = api_key
        self.app_key = app_key
        self.base_url = DD_API_BASE.format(site=site)
        self._headers = {
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": app_key,
            "Content-Type": "application/json",
        }

    async def get_coverage(self, service_name: str) -> DatadogCoverage:
        """
        Fetch all Datadog coverage for a given service.
        Returns a DatadogCoverage object with all available data.
        Gracefully handles missing permissions or service not found.
        """
        coverage = DatadogCoverage(service_name=service_name)

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Fetch metrics
            try:
                metrics = await self._list_metrics(client, service_name)
                coverage.metrics = metrics
            except Exception as e:
                log.warning("dd_metrics_fetch_failed", service=service_name, error=str(e))

            # Fetch monitors
            try:
                monitors = await self._list_monitors(client, service_name)
                coverage.monitors = monitors
            except Exception as e:
                log.warning("dd_monitors_fetch_failed", service=service_name, error=str(e))

            # Check APM
            try:
                apm_services = await self._list_apm_services(client)
                coverage.apm_services = apm_services
                coverage.has_apm = service_name in apm_services
            except Exception as e:
                log.warning("dd_apm_fetch_failed", service=service_name, error=str(e))

        log.info(
            "dd_coverage_fetched",
            service=service_name,
            metrics=len(coverage.metrics),
            monitors=len(coverage.monitors),
            has_apm=coverage.has_apm,
        )
        return coverage

    async def _list_metrics(self, client: httpx.AsyncClient, service_name: str) -> list[str]:
        """List all metrics tagged with the service name."""
        response = await client.get(
            f"{self.base_url}/api/v1/metrics",
            headers=self._headers,
            params={"q": f"service:{service_name}"},
        )
        if response.status_code == 200:
            return response.json().get("metrics", [])
        return []

    async def _list_monitors(self, client: httpx.AsyncClient, service_name: str) -> list[dict]:
        """List monitors related to the service."""
        response = await client.get(
            f"{self.base_url}/api/v1/monitor",
            headers=self._headers,
            params={"tags": f"service:{service_name}", "page_size": 50},
        )
        if response.status_code == 200:
            monitors = response.json()
            return [{"id": m["id"], "name": m["name"], "status": m.get("overall_state")} for m in monitors]
        return []

    async def _list_apm_services(self, client: httpx.AsyncClient) -> list[str]:
        """List all services in APM."""
        response = await client.get(
            f"{self.base_url}/api/v1/services/definitions",
            headers=self._headers,
        )
        if response.status_code == 200:
            data = response.json()
            return [s.get("schema", {}).get("dd-service", "") for s in data.get("data", [])]
        return []

    async def check_red_metrics(self, service_name: str) -> dict[str, bool]:
        """
        Check if a service has RED pattern metrics (Rate, Errors, Duration).
        Returns dict with keys: has_rate, has_errors, has_duration
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            metrics = await self._list_metrics(client, service_name)

        metrics_lower = [m.lower() for m in metrics]
        return {
            "has_rate": any("request" in m or "count" in m or "rate" in m for m in metrics_lower),
            "has_errors": any("error" in m for m in metrics_lower),
            "has_duration": any("duration" in m or "latency" in m or "p99" in m for m in metrics_lower),
        }
