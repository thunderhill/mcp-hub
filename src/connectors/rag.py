from __future__ import annotations

import httpx
import structlog

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from src.core.http_client import get_client, make_error, resilient_request

logger = structlog.get_logger()


class QueryArgs(BaseModel):
    question: str = Field(..., min_length=1, description="The question to ask")
    top_k: int = Field(default=5, gt=0, description="Number of results to return")


class RagConnector:
    name = "rag"
    namespace = "rag"

    def __init__(self, base_url: str, timeout: float = 5.0, retries: int = 2):
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries

    async def _try_openapi(self, mcp: FastMCP) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout)) as client:
                resp = await client.get(f"{self.base_url}/openapi.json")
                resp.raise_for_status()
                await logger.ainfo(
                    "openapi_spec_loaded",
                    upstream="rag",
                    url=f"{self.base_url}/openapi.json",
                )
                return True
        except Exception as exc:
            await logger.awarning(
                "openapi_spec_unreachable",
                upstream="rag",
                url=f"{self.base_url}/openapi.json",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return False

    async def register(self, mcp: FastMCP) -> None:
        await self._try_openapi(mcp)

        client = get_client(self.base_url, self.timeout)
        retries = self.retries

        @mcp.tool()
        async def query(question: str, top_k: int = 5) -> dict | list:
            """Query the Enterprise RAG system."""
            args = QueryArgs(question=question, top_k=top_k)
            try:
                resp = await resilient_request(
                    client, "POST", "/query",
                    upstream="rag", retries=retries,
                    json=args.model_dump(),
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc), upstream="rag")
