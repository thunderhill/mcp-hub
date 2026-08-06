"""
Demo client — connects to mcp-hub, lists tools, and runs available tools.

Usage: uv run python demo_client.py
"""
from __future__ import annotations

import asyncio
import os

from fastmcp import Client


async def main() -> None:
    hub_url = os.environ.get("MCP_HUB_URL", "http://localhost:8000/mcp")
    token = os.environ.get("MCP_AUTH_TOKEN", "dev-token-123")

    headers = {"Authorization": f"Bearer {token}"}

    async with Client(hub_url, headers=headers) as client:
        print("=== Connected to MCP Hub ===\n")

        tools = await client.list_tools()
        print(f"Available tools ({len(tools)}):")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")
        print()

        slack_tools = [t for t in tools if "slack" in t.name.lower() or "send_message" in t.name]
        if slack_tools:
            print("=== Step 1: Get Slack Channels ===")
            result = await client.call_tool("slack_get_channels", {})
            print(f"Channels: {result}\n")

            print("=== Step 2: Send Message to Slack ===")
            result = await client.call_tool(
                "slack_send_message",
                {"channel": "general", "text": "Hello from MCP Hub!"},
            )
            print(f"Send result: {result}\n")

            print("=== Step 3: Get Messages ===")
            result = await client.call_tool(
                "slack_get_messages",
                {"channel": "general"},
            )
            print(f"Messages: {result}\n")

        print("=== Demo complete ===")


if __name__ == "__main__":
    asyncio.run(main())
