"""Fixed, service-scoped read-only queries against demo observability sources."""

import json
import time

import httpx

from .models import SERVICES

DESCRIPTIONS = {
    "query_logs": "Read up to 50 Loki log lines for this service in the last five minutes.",
    "get_metrics": "Read Prometheus latency, memory, SQL duration, and error gauges for this service.",
    "list_deployments": "Read recent demo deployments for this service.",
    "get_deploy_diff": "Read the latest demo deployment diff for this service.",
}


class ObservabilityTools:
    def __init__(self, settings):
        self.settings = settings

    @staticmethod
    def read(base_url, path, params):
        # URLs come from operator configuration; models cannot set URLs or query strings.
        with httpx.Client(timeout=5, follow_redirects=False) as client:
            with client.stream("GET", base_url.rstrip("/") + path, params=params) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 262144:
                        raise ValueError("Observability response exceeds 256 KiB")

                return json.loads(body)

    def logs(self, service):
        end = time.time_ns()
        data = self.read(
            self.settings.loki_url,
            "/loki/api/v1/query_range",
            {
                "query": '{service="' + service + '"}',
                "start": str(end - 300_000_000_000),
                "end": str(end),
                "limit": "50",
                "direction": "backward",
            },
        )
        if data.get("status") != "success":
            raise ValueError("Loki query failed")
        return {"source": "loki", "window_seconds": 300, "streams": data["data"]["result"][:50]}

    def metrics(self, service):
        query = (
            '{__name__=~"demo_fill_latency_ms|demo_sql_duration_ms|demo_memory_bytes|'
            'demo_error_ratio",service="' + service + '"}'
        )
        data = self.read(
            self.settings.prometheus_url, "/api/v1/query", {"query": query, "timeout": "3s"}
        )
        if data.get("status") != "success":
            raise ValueError("Prometheus query failed")
        return {
            "source": "prometheus",
            "result": data["data"]["result"][:20],
            "warnings": data.get("warnings", []),
        }

    def deployments(self, service):
        return self.read(self.settings.demo_service_url, "/deployments", {"service": service})

    def diff(self, service):
        return self.read(
            self.settings.demo_service_url, "/deployments/latest/diff", {"service": service}
        )

    def tools(self, service):
        if service not in SERVICES:
            raise ValueError("Unknown service scope")
        tools = {}
        if self.settings.loki_url:
            tools["query_logs"] = lambda: self.logs(service)
        if self.settings.prometheus_url:
            tools["get_metrics"] = lambda: self.metrics(service)
        if self.settings.demo_service_url:
            tools["list_deployments"] = lambda: self.deployments(service)
            tools["get_deploy_diff"] = lambda: self.diff(service)
        return tools
