from __future__ import annotations

import asyncio
from typing import Any

import socketio
import structlog
from pydantic import BaseModel, Field

from fastmcp import FastMCP

from src.core.http_client import make_error

logger = structlog.get_logger()


class SendMessageArgs(BaseModel):
    channel: str = Field(..., min_length=1, description="Channel name")
    text: str = Field(..., min_length=1, description="Message text")


class GetMessagesArgs(BaseModel):
    channel: str = Field(..., min_length=1, description="Channel name")


class SlackConnector:
    name = "minislack"
    namespace = "slack"

    def __init__(self, base_url: str, timeout: float = 5.0, retries: int = 2):
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries
        self._sio: socketio.AsyncClient | None = None
        self._connected = False
        self._channels: list[str] = []
        self._history: dict[str, list[dict]] = {}
        self._history_event = asyncio.Event()
        self._login_event = asyncio.Event()
        self._login_ok = False
        self._username = "mcp-hub-bot"

    async def _ensure_connected(self) -> socketio.AsyncClient:
        if self._sio and self._connected:
            return self._sio

        sio = socketio.AsyncClient(reconnection=True, reconnection_attempts=self.retries)

        @sio.on("login_response")
        async def on_login(data: dict) -> None:
            if data.get("ok"):
                self._login_ok = True
                self._channels = data.get("channels", [])
                await logger.ainfo("minislack_login_ok", username=self._username)
            else:
                self._login_ok = False
                await logger.awarning("minislack_login_failed", error=data.get("error"))
            self._login_event.set()

        @sio.on("channel_history")
        async def on_history(data: dict) -> None:
            channel = data.get("channel", "")
            self._history[channel] = data.get("messages", [])
            self._history_event.set()

        @sio.on("new_message")
        async def on_message(msg: dict) -> None:
            channel = msg.get("channel", "")
            self._history.setdefault(channel, []).append(msg)

        @sio.on("user_list")
        async def on_users(data: dict) -> None:
            pass

        try:
            await sio.connect(self.base_url, transports=["websocket", "polling"])
            self._sio = sio
            self._connected = True

            self._login_event.clear()
            await sio.emit("login", {"username": self._username, "password": "bot"})
            await asyncio.wait_for(self._login_event.wait(), timeout=self.timeout)

            if not self._login_ok:
                raise ConnectionError("MiniSlack login failed")

        except Exception as exc:
            self._connected = False
            await logger.aerror("minislack_connect_failed", error=str(exc))
            raise

        return sio

    async def register(self, mcp: FastMCP) -> None:
        connector = self

        @mcp.tool()
        async def send_message(channel: str, text: str) -> dict:
            """Send a message to a MiniSlack channel."""
            args = SendMessageArgs(channel=channel, text=text)
            try:
                sio = await connector._ensure_connected()
                await sio.emit("send_message", {
                    "channel": args.channel,
                    "text": args.text,
                })
                return {"ok": True, "channel": args.channel, "text": args.text}
            except Exception as exc:
                return make_error(str(exc), upstream="minislack")

        @mcp.tool()
        async def get_messages(channel: str) -> dict | list:
            """Get message history from a MiniSlack channel."""
            args = GetMessagesArgs(channel=channel)
            try:
                sio = await connector._ensure_connected()
                connector._history_event.clear()
                connector._history.pop(args.channel, None)
                await sio.emit("join_channel", {"channel": args.channel})
                await asyncio.wait_for(
                    connector._history_event.wait(),
                    timeout=connector.timeout,
                )
                return connector._history.get(args.channel, [])
            except Exception as exc:
                return make_error(str(exc), upstream="minislack")

        @mcp.tool()
        async def get_channels() -> dict | list:
            """List all MiniSlack channels."""
            try:
                await connector._ensure_connected()
                return {"channels": connector._channels}
            except Exception as exc:
                return make_error(str(exc), upstream="minislack")
