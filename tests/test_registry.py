import pytest
import respx
from httpx import Response

from fastmcp import Client

from src.core.registry import build_hub


@pytest.mark.asyncio
async def test_disabled_service_not_mounted(tmp_path):
    config = tmp_path / "services.yaml"
    config.write_text(
        """
services:
  - name: minislack
    namespace: slack
    type: socketio
    base_url: http://127.0.0.1:5000
    enabled: true
  - name: observability
    namespace: obs
    type: rest
    base_url: http://127.0.0.1:3000
    enabled: false
  - name: rag
    namespace: rag
    type: openapi
    base_url: http://127.0.0.1:9003
    enabled: false
"""
    )

    hub = await build_hub(config)

    async with Client(hub) as client:
        tools = await client.list_tools()
        tool_names = [t.name for t in tools]

        assert any("send_message" in n for n in tool_names)
        assert not any("get_dashboards" in n for n in tool_names)
        assert not any("query" in n for n in tool_names)


@pytest.mark.asyncio
async def test_only_enabled_services_mount(tmp_path):
    config = tmp_path / "services.yaml"
    config.write_text(
        """
services:
  - name: minislack
    namespace: slack
    type: socketio
    base_url: http://127.0.0.1:5000
    enabled: false
  - name: observability
    namespace: obs
    type: rest
    base_url: http://127.0.0.1:3000
    enabled: false
"""
    )

    hub = await build_hub(config)

    async with Client(hub) as client:
        tools = await client.list_tools()
        assert len(tools) == 0
