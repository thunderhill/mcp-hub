"""Workspace-level MiniSlack tools.

Rewritten alongside the connector. The previous tests reached into Socket.IO
internals — `connector._sio`, `_connected`, `_login_ok` — and so could only
ever prove the mock behaved like the mock. These drive the real HTTP surface
through respx, which is the thing that can actually break.
"""
from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from fastmcp import Client, FastMCP

from src.connectors.slack import SlackConnector

MINISLACK = "http://minislack.test"


async def mount(monkeypatch) -> FastMCP:
    monkeypatch.setenv("MINISLACK_TOKEN_OPS", "msk_ops")
    hub = FastMCP("slack")
    await SlackConnector(MINISLACK).register(hub)
    return hub


def payload(result) -> dict:
    if getattr(result, "structured_content", None):
        return result.structured_content
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
@respx.mock
async def test_send_message_uses_bearer_not_socketio_login(monkeypatch):
    route = respx.post(f"{MINISLACK}/api/v1/channels/torque-ops/messages").mock(
        return_value=Response(200, json={"message": {"id": 7}})
    )
    hub = await mount(monkeypatch)

    async with Client(hub) as client:
        body = payload(
            await client.call_tool(
                "send_message", {"channel": "torque-ops", "text": "hello"}
            )
        )

    assert body["ok"] is True
    assert body["message_id"] == "7"
    assert route.calls.last.request.headers["authorization"] == "Bearer msk_ops"


@pytest.mark.asyncio
@respx.mock
async def test_get_channels(monkeypatch):
    respx.get(f"{MINISLACK}/api/v1/channels").mock(
        return_value=Response(200, json={"channels": ["email-outbox", "torque-ops"]})
    )
    hub = await mount(monkeypatch)

    async with Client(hub) as client:
        body = payload(await client.call_tool("get_channels", {}))

    assert "email-outbox" in body["channels"]


@pytest.mark.asyncio
@respx.mock
async def test_whoami_identifies_the_agent(monkeypatch):
    respx.get(f"{MINISLACK}/api/v1/me").mock(
        return_value=Response(200, json={"user": {"username": "mcp-hub-ops"}})
    )
    hub = await mount(monkeypatch)

    async with Client(hub) as client:
        body = payload(await client.call_tool("whoami", {}))

    assert body["user"]["username"] == "mcp-hub-ops"


@pytest.mark.asyncio
@respx.mock
async def test_upstream_failure_returns_error_not_exception(monkeypatch):
    respx.get(f"{MINISLACK}/api/v1/channels").mock(
        return_value=Response(503, json={"error": "down"})
    )
    hub = await mount(monkeypatch)

    async with Client(hub) as client:
        body = payload(await client.call_tool("get_channels", {}))

    # Degraded, not crashed: one dead upstream must never take the hub with it.
    assert body["upstream"] == "minislack"
    assert "error" in body


@pytest.mark.asyncio
async def test_missing_token_is_reported(monkeypatch):
    monkeypatch.delenv("MINISLACK_TOKEN_OPS", raising=False)
    monkeypatch.delenv("MINISLACK_TOKEN_EMAIL", raising=False)
    hub = FastMCP("slack")
    await SlackConnector(MINISLACK).register(hub)

    async with Client(hub) as client:
        body = payload(await client.call_tool("get_channels", {}))

    assert "MINISLACK_TOKEN_OPS" in body["error"]
