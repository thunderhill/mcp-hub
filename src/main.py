from __future__ import annotations

import asyncio
import os

from src.core.logging import setup_logging


async def main() -> None:
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))

    from src.core.registry import build_hub

    hub = await build_hub()

    port = int(os.environ.get("MCP_PORT", "8000"))

    await hub.run_async(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
        path="/mcp",
        stateless_http=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
