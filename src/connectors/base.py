from __future__ import annotations

from typing import Protocol, runtime_checkable

from fastmcp import FastMCP


@runtime_checkable
class Connector(Protocol):
    name: str
    namespace: str

    async def register(self, mcp: FastMCP) -> None: ...
