import pytest
import respx
from httpx import Response

from fastmcp import FastMCP, Client

from src.connectors.rag import RagConnector


@pytest.mark.asyncio
async def test_rag_query():
    with respx.mock(base_url="http://127.0.0.1:9003") as mock:
        mock.get("/openapi.json").mock(return_value=Response(200, json={"openapi": "3.0.0"}))
        mock.post("/query").mock(
            return_value=Response(200, json={"results": [{"text": "answer", "score": 0.9}]})
        )

        sub = FastMCP("rag")
        connector = RagConnector("http://127.0.0.1:9003")
        await connector.register(sub)

        async with Client(sub) as client:
            result = await client.call_tool("query", {"question": "What is MCP?", "top_k": 3})
            assert "answer" in str(result)


@pytest.mark.asyncio
async def test_rag_graceful_degradation():
    with respx.mock(base_url="http://127.0.0.1:9003", assert_all_called=False) as mock:
        mock.get("/openapi.json").mock(side_effect=Exception("connection refused"))

        sub = FastMCP("rag")
        connector = RagConnector("http://127.0.0.1:9003")
        await connector.register(sub)

        async with Client(sub) as client:
            tools = await client.list_tools()
            assert any(t.name == "query" for t in tools)


@pytest.mark.asyncio
async def test_rag_query_upstream_error():
    with respx.mock(base_url="http://127.0.0.1:9003") as mock:
        mock.get("/openapi.json").mock(return_value=Response(200, json={"openapi": "3.0.0"}))
        mock.post("/query").mock(return_value=Response(503, json={"error": "unavailable"}))

        sub = FastMCP("rag")
        connector = RagConnector("http://127.0.0.1:9003", retries=0)
        await connector.register(sub)

        async with Client(sub) as client:
            result = await client.call_tool("query", {"question": "test", "top_k": 1})
            assert "error" in str(result)
