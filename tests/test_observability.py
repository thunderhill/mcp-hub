import pytest
import respx
from httpx import Response

from fastmcp import FastMCP, Client

from src.connectors.observability import ObservabilityConnector


@pytest.mark.asyncio
async def test_get_dashboards():
    with respx.mock(base_url="http://127.0.0.1:3000") as mock:
        mock.get("/api/search").mock(
            return_value=Response(200, json=[{"uid": "abc", "title": "System"}])
        )

        sub = FastMCP("obs")
        connector = ObservabilityConnector("http://127.0.0.1:3000")
        await connector.register(sub)

        async with Client(sub) as client:
            result = await client.call_tool("get_dashboards", {})
            assert "System" in str(result)


@pytest.mark.asyncio
async def test_get_alerts():
    with respx.mock(base_url="http://127.0.0.1:3000") as mock:
        mock.get("/api/alerts").mock(
            return_value=Response(200, json=[{"name": "HighCPU", "state": "alerting"}])
        )

        sub = FastMCP("obs")
        connector = ObservabilityConnector("http://127.0.0.1:3000")
        await connector.register(sub)

        async with Client(sub) as client:
            result = await client.call_tool("get_alerts", {})
            assert "HighCPU" in str(result)


@pytest.mark.asyncio
async def test_query_prometheus():
    with respx.mock(base_url="http://127.0.0.1:3000") as mock:
        mock.get("/api/datasources/proxy/1/api/v1/query").mock(
            return_value=Response(200, json={"status": "success", "data": {"result": []}})
        )

        sub = FastMCP("obs")
        connector = ObservabilityConnector("http://127.0.0.1:3000")
        await connector.register(sub)

        async with Client(sub) as client:
            result = await client.call_tool("query_prometheus", {"query": "up"})
            assert "success" in str(result)


@pytest.mark.asyncio
async def test_get_datasources():
    with respx.mock(base_url="http://127.0.0.1:3000") as mock:
        mock.get("/api/datasources").mock(
            return_value=Response(200, json=[{"name": "Prometheus", "type": "prometheus"}])
        )

        sub = FastMCP("obs")
        connector = ObservabilityConnector("http://127.0.0.1:3000")
        await connector.register(sub)

        async with Client(sub) as client:
            result = await client.call_tool("get_datasources", {})
            assert "Prometheus" in str(result)
