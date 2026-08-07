from __future__ import annotations

import os
from pathlib import Path

import structlog
import uvicorn
from starlette.middleware import Middleware

from src.core.auth import BearerTokenMiddleware
from src.core.logging import setup_logging

logger = structlog.get_logger()


def build_app():
    """Assemble the ASGI app.

    Served through `http_app()` rather than `run_async()` because three things
    this hub needs are only reachable that way:

      middleware      BearerTokenMiddleware was defined but never wired, so
                      MCP_AUTH_TOKEN was not being enforced at all.
      json_response   FastMCP otherwise answers tools/call with
                      text/event-stream. SSE framing buys nothing for a
                      request/response tool call and breaks any client that
                      reasonably calls .json() on the reply.
      stateless_http  No initialize handshake and no session id, so a caller
                      can POST a single tools/call. That is what makes TORQUE's
                      delivery client twenty lines instead of a session
                      manager.
    """
    import asyncio

    from src.core.registry import build_hub

    hub = asyncio.run(build_hub())

    return hub.http_app(
        path="/mcp",
        middleware=[Middleware(BearerTokenMiddleware)],
        json_response=True,
        stateless_http=True,
        # The hub is reached across the LAN by its IP during the multi-laptop
        # demo. FastMCP's DNS-rebinding protection rejects a Host header it
        # does not recognise, which would present as a confusing 4xx from a
        # teammate's machine while localhost worked fine.
        host_origin_protection=False,
    )


def main() -> None:
    # Tokens and addresses live in .env, which is gitignored. Loaded before
    # anything reads os.environ — the connectors resolve their tokens lazily,
    # but MCP_PORT and MCP_AUTH_TOKEN are read here.
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))

    # 8001, not 8000: the TML backend already holds 8000 on the dev laptop.
    port = int(os.environ.get("MCP_PORT", "8001"))
    host = os.environ.get("MCP_HOST", "0.0.0.0")

    app = build_app()
    logger.info("hub_starting", host=host, port=port, path="/mcp")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
