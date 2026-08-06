"""
Template connector — copy this file to create a new connector.

Steps:
  1. Copy this file to src/connectors/<your_service>.py
  2. Rename the class and update `name` / `namespace`
  3. Add your tools inside `register()`
  4. Add an entry in config/services.yaml:
       - name: your_service
         namespace: your_ns
         type: rest
         base_url: http://your-service:PORT
         enabled: true
  5. Map the connector in src/core/registry.py CONNECTOR_MAP
"""
from __future__ import annotations

from fastmcp import FastMCP

from src.core.http_client import get_client, make_error, resilient_request


class TemplateConnector:
    name = "template_service"
    namespace = "template"

    def __init__(self, base_url: str, timeout: float = 5.0, retries: int = 2):
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries

    async def register(self, mcp: FastMCP) -> None:
        client = get_client(self.base_url, self.timeout)
        retries = self.retries

        @mcp.tool()
        async def example_tool(param: str) -> dict:
            """Describe what this tool does."""
            try:
                resp = await resilient_request(
                    client, "GET", "/example",
                    upstream=self.name, retries=retries,
                    params={"param": param},
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc), upstream=self.name)
