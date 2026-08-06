import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastmcp import FastMCP, Client

from src.connectors.slack import SlackConnector


def _make_mock_sio(channels=None, history=None):
    """Create a mock socketio.AsyncClient that simulates MiniSlack."""
    channels = channels or ["general", "random"]
    history = history or [{"user": "alice", "text": "hi", "ts": "12:00", "channel": "general"}]

    mock_sio = AsyncMock()
    mock_sio.connected = True
    handlers = {}

    async def fake_on(event, handler=None):
        if handler:
            handlers[event] = handler

    def sync_on(event):
        def decorator(fn):
            handlers[event] = fn
            return fn
        return decorator

    mock_sio.on = sync_on

    async def fake_connect(*a, **kw):
        pass

    mock_sio.connect = fake_connect

    async def fake_emit(event, data=None):
        if event == "login":
            if "login_response" in handlers:
                await handlers["login_response"]({"ok": True, "channels": channels})
        elif event == "join_channel":
            if "channel_history" in handlers:
                ch = data.get("channel", "general") if data else "general"
                await handlers["channel_history"]({"channel": ch, "messages": history})

    mock_sio.emit = fake_emit

    return mock_sio


@pytest.mark.asyncio
async def test_send_message():
    connector = SlackConnector("http://127.0.0.1:5000")
    mock_sio = _make_mock_sio()
    sub = FastMCP("slack")
    await connector.register(sub)

    connector._sio = mock_sio
    connector._connected = True
    connector._login_ok = True
    connector._channels = ["general", "random"]

    async with Client(sub) as client:
        result = await client.call_tool("send_message", {"channel": "general", "text": "hello"})
        assert "ok" in str(result)


@pytest.mark.asyncio
async def test_get_channels():
    connector = SlackConnector("http://127.0.0.1:5000")
    sub = FastMCP("slack")
    await connector.register(sub)

    connector._sio = AsyncMock()
    connector._connected = True
    connector._login_ok = True
    connector._channels = ["general", "random", "dev"]

    async with Client(sub) as client:
        result = await client.call_tool("get_channels", {})
        text = str(result)
        assert "general" in text
        assert "dev" in text
