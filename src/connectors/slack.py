"""MiniSlack workspace connector — the operator's view, not a channel.

Rewritten from Socket.IO to REST + Bearer.

The previous implementation opened a Socket.IO connection and emitted
``login`` with ``{"username": "mcp-hub-bot", "password": "bot"}``. That is
MiniSlack's *human browser* path: it takes a seat in the workspace, it depends
on an event ordering designed for a UI (waiting on ``login_response`` and
``channel_history`` events with timeouts), and it makes every tool call
stateful against a socket that may have silently dropped.

Agents authenticate with a minted token against ``/api/v1``. That path is
request/response, has no login step to race, returns real HTTP status codes,
and is attributable per agent in the upstream's own logs.

Channel *delivery* does not belong here — that is `channels.py`, one namespace
per marketing channel with its own token. What is left is the workspace-level
view an operator wants: which channels exist, who am I, read a channel back.
"""
from __future__ import annotations

import os
from typing import Any

import structlog

from fastmcp import FastMCP

from src.core.http_client import get_client, make_error, resilient_request

logger = structlog.get_logger()

# The ops token is separate from the five channel tokens on purpose: a human
# browsing the workspace should not consume the rate budget a campaign needs
# to finish its fan-out.
TOKEN_ENV = "MINISLACK_TOKEN_OPS"
FALLBACK_TOKEN_ENV = "MINISLACK_TOKEN_EMAIL"


class SlackConnector:
    name = "minislack"
    namespace = "slack"

    def __init__(self, base_url: str, timeout: float = 5.0, retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries

    @property
    def token(self) -> str:
        """Read at call time so a late-set variable still works.

        Falls back to a channel token rather than failing outright: read-only
        workspace calls are harmless on any valid agent identity, and an
        operator debugging a demo should not be blocked by one more variable.
        """
        return os.environ.get(TOKEN_ENV) or os.environ.get(FALLBACK_TOKEN_ENV, "")

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def register(self, mcp: FastMCP) -> None:
        connector = self
        client = get_client(self.base_url, self.timeout)

        def _need_token() -> dict[str, Any] | None:
            if connector.token:
                return None
            return make_error(
                f"no agent token — set {TOKEN_ENV}",
                upstream="minislack",
                retryable=False,
            )

        @mcp.tool()
        async def get_channels() -> dict:
            """List the channels in the MiniSlack workspace."""
            if (err := _need_token()) is not None:
                return err
            try:
                resp = await resilient_request(
                    client, "GET", "/api/v1/channels",
                    upstream=connector.name, retries=connector.retries,
                    headers=connector._auth(),
                )
                payload = resp.json()
                return payload if isinstance(payload, dict) else {"channels": payload}
            except Exception as exc:
                return make_error(str(exc)[:200], upstream="minislack")

        @mcp.tool()
        async def get_messages(channel: str, limit: int = 50) -> dict:
            """Read recent messages from a MiniSlack channel."""
            if (err := _need_token()) is not None:
                return err
            try:
                resp = await resilient_request(
                    client, "GET", f"/api/v1/channels/{channel}/messages",
                    upstream=connector.name, retries=connector.retries,
                    headers=connector._auth(), params={"limit": limit},
                )
                payload = resp.json()
                messages = (
                    payload.get("messages", payload)
                    if isinstance(payload, dict)
                    else payload
                )
                return {"channel": channel, "count": len(messages), "messages": messages}
            except Exception as exc:
                return make_error(str(exc)[:200], upstream="minislack")

        @mcp.tool()
        async def send_message(channel: str, text: str) -> dict:
            """Post to an arbitrary MiniSlack channel.

            This is the operator escape hatch — an ops note, a demo
            annotation. Campaign delivery goes through the per-channel
            namespaces (``email.send`` and friends), which carry the right
            token and the right rate budget for a fan-out.
            """
            if (err := _need_token()) is not None:
                return err
            try:
                resp = await resilient_request(
                    client, "POST", f"/api/v1/channels/{channel}/messages",
                    upstream=connector.name, retries=connector.retries,
                    headers=connector._auth(), json={"text": text},
                )
                body = resp.json()
                return {
                    "ok": True,
                    "channel": channel,
                    "message_id": str(body.get("message", {}).get("id", "")),
                }
            except Exception as exc:
                return make_error(str(exc)[:200], upstream="minislack")

        @mcp.tool()
        async def whoami() -> dict:
            """Identify the agent this connector authenticates as."""
            if (err := _need_token()) is not None:
                return err
            try:
                resp = await resilient_request(
                    client, "GET", "/api/v1/me",
                    upstream=connector.name, retries=0,
                    headers=connector._auth(),
                )
                return resp.json()
            except Exception as exc:
                return make_error(str(exc)[:200], upstream="minislack")
