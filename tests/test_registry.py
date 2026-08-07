import pytest
import respx
from httpx import Response

from fastmcp import Client

from src.core.registry import build_hub, expand_env


@pytest.mark.asyncio
async def test_shipped_config_mounts_all_five_channel_namespaces():
    """The real config/services.yaml, not a fixture.

    TORQUE calls `email.send` by that literal string. If a namespace is
    dropped, renamed, or FastMCP changes its separator, delivery for that
    channel fails silently — the campaign reports a send that never happened.
    Asserting against the shipped file is the only version of this test that
    can catch a config edit.
    """
    hub = await build_hub()

    async with Client(hub) as client:
        names = {t.name for t in await client.list_tools()}

    for channel in ("email", "whatsapp", "sms", "push", "social"):
        assert f"{channel}.send" in names, f"{channel}.send missing"
        assert f"{channel}.status" in names
        assert f"{channel}.history" in names


def test_env_interpolation_prefers_environment_over_default(monkeypatch):
    monkeypatch.setenv("MINISLACK_URL", "http://172.25.86.228:5000")
    assert (
        expand_env("${MINISLACK_URL:-http://127.0.0.1:5000}")
        == "http://172.25.86.228:5000"
    )

    monkeypatch.delenv("MINISLACK_URL", raising=False)
    assert (
        expand_env("${MINISLACK_URL:-http://127.0.0.1:5000}")
        == "http://127.0.0.1:5000"
    )


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
