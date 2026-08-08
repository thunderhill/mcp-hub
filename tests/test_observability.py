"""Grafana connector.

Every existing test here was passing against a connector that sent no
authentication header at all — respx doesn't care whether a mocked route
asserts on headers unless told to, so the missing-auth bug (see the module
docstring in src/connectors/observability.py) survived undetected. These now
assert on the Authorization header explicitly, and add the failure case that
matters most in practice: no token configured, which must produce a clear
per-call error rather than a 401 the caller has to decode.
"""
import pytest
import respx
from httpx import Response

from fastmcp import FastMCP, Client

from src.connectors.observability import ObservabilityConnector


async def build(monkeypatch) -> FastMCP:
    monkeypatch.setenv("GRAFANA_API_TOKEN", "glsa_test_token")
    sub = FastMCP("obs")
    await ObservabilityConnector("http://127.0.0.1:3000").register(sub)
    return sub


@pytest.mark.asyncio
@respx.mock
async def test_get_dashboards_sends_bearer_token(monkeypatch):
    route = respx.get("http://127.0.0.1:3000/api/search").mock(
        return_value=Response(200, json=[{"uid": "abc", "title": "System"}])
    )
    sub = await build(monkeypatch)

    async with Client(sub) as client:
        result = await client.call_tool("get_dashboards", {})
        assert "System" in str(result)

    assert route.calls.last.request.headers["authorization"] == "Bearer glsa_test_token"


@pytest.mark.asyncio
@respx.mock
async def test_get_alerts_uses_the_unified_alertmanager_api(monkeypatch):
    """/api/alerts is the pre-unified-alerting endpoint and 404s on any
    current Grafana; get_alerts must target the alertmanager-compatible v2
    API that replaced it."""
    respx.get("http://127.0.0.1:3000/api/alertmanager/grafana/api/v2/alerts").mock(
        return_value=Response(200, json=[{"labels": {"alertname": "HighCPU"}}])
    )
    sub = await build(monkeypatch)

    async with Client(sub) as client:
        result = await client.call_tool("get_alerts", {})
        assert "HighCPU" in str(result)


@pytest.mark.asyncio
@respx.mock
async def test_query_prometheus_targets_the_pinned_uid_not_a_numeric_id(monkeypatch):
    """Numeric datasource ids are assigned by insertion order and are not
    stable across a reprovision. The provisioned datasource carries
    uid: prometheus (observability/provisioning/datasources/prometheus.yml);
    this must be what the connector actually calls."""
    route = respx.get(
        "http://127.0.0.1:3000/api/datasources/proxy/uid/prometheus/api/v1/query"
    ).mock(return_value=Response(200, json={"status": "success", "data": {"result": []}}))
    sub = await build(monkeypatch)

    async with Client(sub) as client:
        result = await client.call_tool("query_prometheus", {"query": "up"})
        assert "success" in str(result)
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_query_loki_targets_the_pinned_uid(monkeypatch):
    route = respx.get(
        "http://127.0.0.1:3000/api/datasources/proxy/uid/loki/loki/api/v1/query_range"
    ).mock(return_value=Response(200, json={"status": "success"}))
    sub = await build(monkeypatch)

    async with Client(sub) as client:
        await client.call_tool("query_loki", {"query": '{job="torque"}'})
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_get_datasources(monkeypatch):
    respx.get("http://127.0.0.1:3000/api/datasources").mock(
        return_value=Response(200, json=[{"name": "Prometheus", "type": "prometheus"}])
    )
    sub = await build(monkeypatch)

    async with Client(sub) as client:
        result = await client.call_tool("get_datasources", {})
        assert "Prometheus" in str(result)


@pytest.mark.asyncio
async def test_missing_token_fails_one_call_with_a_clear_message(monkeypatch):
    """No Grafana call should ever be attempted without a token — this is the
    graceful-degradation contract every other connector in the hub follows."""
    monkeypatch.delenv("GRAFANA_API_TOKEN", raising=False)
    sub = FastMCP("obs")
    await ObservabilityConnector("http://127.0.0.1:3000").register(sub)

    async with Client(sub) as client:
        for tool in ("get_dashboards", "get_datasources", "get_alerts"):
            result = await client.call_tool(tool, {})
            text = str(result)
            assert "GRAFANA_API_TOKEN" in text, f"{tool} did not report the missing token"

        result = await client.call_tool("query_prometheus", {"query": "up"})
        assert "GRAFANA_API_TOKEN" in str(result)
