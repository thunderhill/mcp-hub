from __future__ import annotations

from pydantic import BaseModel, Field

from fastmcp import FastMCP

from src.core.http_client import get_client, make_error, resilient_request


class GetMetricsArgs(BaseModel):
    query: str = Field(..., min_length=1, description="PromQL query")
    step: str = Field(default="60s", description="Query step interval")


class SearchLogsArgs(BaseModel):
    query: str = Field(..., min_length=1, description="LogQL query")
    limit: int = Field(default=100, gt=0, description="Max log lines to return")


class ObservabilityConnector:
    name = "observability"
    namespace = "obs"

    def __init__(self, base_url: str, timeout: float = 5.0, retries: int = 2):
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries

    async def register(self, mcp: FastMCP) -> None:
        grafana_client = get_client(self.base_url, self.timeout)
        retries = self.retries

        @mcp.tool()
        async def get_dashboards() -> dict | list:
            """List all Grafana dashboards."""
            try:
                resp = await resilient_request(
                    grafana_client, "GET", "/api/search",
                    upstream="grafana", retries=retries,
                    params={"type": "dash-db"},
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc), upstream="grafana")

        @mcp.tool()
        async def get_datasources() -> dict | list:
            """List all Grafana datasources (Prometheus, Loki, etc.)."""
            try:
                resp = await resilient_request(
                    grafana_client, "GET", "/api/datasources",
                    upstream="grafana", retries=retries,
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc), upstream="grafana")

        @mcp.tool()
        async def query_prometheus(query: str, step: str = "60s") -> dict | list:
            """Run a PromQL query via Grafana's Prometheus datasource proxy."""
            args = GetMetricsArgs(query=query, step=step)
            try:
                resp = await resilient_request(
                    grafana_client, "GET",
                    "/api/datasources/proxy/1/api/v1/query",
                    upstream="prometheus-via-grafana", retries=retries,
                    params={"query": args.query},
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc), upstream="prometheus-via-grafana")

        @mcp.tool()
        async def query_loki(query: str, limit: int = 100) -> dict | list:
            """Run a LogQL query via Grafana's Loki datasource proxy."""
            args = SearchLogsArgs(query=query, limit=limit)
            try:
                resp = await resilient_request(
                    grafana_client, "GET",
                    "/api/datasources/proxy/2/loki/api/v1/query_range",
                    upstream="loki-via-grafana", retries=retries,
                    params={"query": args.query, "limit": args.limit},
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc), upstream="loki-via-grafana")

        @mcp.tool()
        async def get_alerts() -> dict | list:
            """Get current Grafana alerts."""
            try:
                resp = await resilient_request(
                    grafana_client, "GET", "/api/alerts",
                    upstream="grafana", retries=retries,
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc), upstream="grafana")
