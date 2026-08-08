"""Grafana / Prometheus connector.

Fixed while wiring it up against a real Grafana for the first time. Two bugs
existed from the day this file was written, and both were invisible until
there was something real to fail against:

  1. Every call sent NO authentication header at all. Grafana rejects
     unauthenticated API calls by default, so every tool here — get_dashboards,
     query_prometheus, everything — would have 401'd from the first real use.
  2. `query_prometheus` and `query_loki` hardcoded numeric datasource proxy ids
     (``/api/datasources/proxy/1/...`` and ``/2/...``). Numeric ids are
     assigned by insertion order and are NOT stable across a reprovision —
     add one more datasource before Prometheus, or provision in a different
     order on a teammate's laptop, and both tools silently point at the wrong
     backend. The provisioned datasource now carries a pinned ``uid:
     prometheus`` (see observability/provisioning/datasources/prometheus.yml),
     and this connector targets that uid, which survives reprovisioning.

Loki is not stood up in this round — there is no ``uid: loki`` datasource
provisioned — so `query_loki` will reach Grafana successfully and then fail
with "datasource not found", which is the correct, honest failure rather than
a silent no-op.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from fastmcp import FastMCP

from src.core.http_client import get_client, make_error, resilient_request

# Set once Grafana is up, via a service-account token — see
# observability/setup.ps1's post-launch step and QUICKSTART.md. Read lazily,
# like every other token in this project, so a missing value fails one call
# with a clear message rather than one mount at boot.
TOKEN_ENV = "GRAFANA_API_TOKEN"


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

    @property
    def token(self) -> str:
        return os.environ.get(TOKEN_ENV, "")

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def register(self, mcp: FastMCP) -> None:
        connector = self
        grafana_client = get_client(self.base_url, self.timeout)
        retries = self.retries

        def _need_token() -> dict | None:
            if connector.token:
                return None
            return make_error(
                f"no Grafana API token — set {TOKEN_ENV}",
                upstream="grafana",
                retryable=False,
            )

        @mcp.tool()
        async def get_dashboards() -> dict | list:
            """List all Grafana dashboards."""
            if (err := _need_token()) is not None:
                return err
            try:
                resp = await resilient_request(
                    grafana_client, "GET", "/api/search",
                    upstream="grafana", retries=retries,
                    headers=connector._auth(),
                    params={"type": "dash-db"},
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc), upstream="grafana")

        @mcp.tool()
        async def get_datasources() -> dict | list:
            """List all Grafana datasources (Prometheus, Loki, etc.)."""
            if (err := _need_token()) is not None:
                return err
            try:
                resp = await resilient_request(
                    grafana_client, "GET", "/api/datasources",
                    upstream="grafana", retries=retries,
                    headers=connector._auth(),
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc), upstream="grafana")

        @mcp.tool()
        async def query_prometheus(query: str, step: str = "60s") -> dict | list:
            """Run a PromQL query via Grafana's Prometheus datasource proxy."""
            if (err := _need_token()) is not None:
                return err
            args = GetMetricsArgs(query=query, step=step)
            try:
                resp = await resilient_request(
                    grafana_client, "GET",
                    "/api/datasources/proxy/uid/prometheus/api/v1/query",
                    upstream="prometheus-via-grafana", retries=retries,
                    headers=connector._auth(),
                    params={"query": args.query},
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc), upstream="prometheus-via-grafana")

        @mcp.tool()
        async def query_loki(query: str, limit: int = 100) -> dict | list:
            """Run a LogQL query via Grafana's Loki datasource proxy.

            Not provisioned in this deployment — no ``uid: loki`` datasource
            exists, so this reaches Grafana and returns a structured "not
            found" error rather than silently no-op-ing. Stood up here as
            designed-for, not built, matching the project's other scope cuts.
            """
            if (err := _need_token()) is not None:
                return err
            args = SearchLogsArgs(query=query, limit=limit)
            try:
                resp = await resilient_request(
                    grafana_client, "GET",
                    "/api/datasources/proxy/uid/loki/loki/api/v1/query_range",
                    upstream="loki-via-grafana", retries=retries,
                    headers=connector._auth(),
                    params={"query": args.query, "limit": args.limit},
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc), upstream="loki-via-grafana")

        @mcp.tool()
        async def get_alerts() -> dict | list:
            """Get current Grafana alerts."""
            if (err := _need_token()) is not None:
                return err
            try:
                resp = await resilient_request(
                    grafana_client, "GET", "/api/alertmanager/grafana/api/v2/alerts",
                    upstream="grafana", retries=retries,
                    headers=connector._auth(),
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc), upstream="grafana")
