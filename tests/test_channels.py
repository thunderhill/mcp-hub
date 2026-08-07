"""The five marketing-channel namespaces.

What these assert, in order of what would actually hurt if it broke:

  1. Each namespace exposes exactly `<ns>.send`, `<ns>.status`, `<ns>.history`
     — TORQUE calls `email.send` by that literal string, so a renamed or
     re-separated tool is a silent delivery outage.
  2. Each namespace posts to ITS OWN outbox with ITS OWN token. Five
     namespaces quietly sharing one token is the failure this design exists to
     prevent, and it looks identical to success until the rate limit hits.
  3. An upstream failure returns a structured error rather than raising, so
     one dead channel cannot take the hub or the other four down.
"""
from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from fastmcp import Client, FastMCP

from src.connectors.channels import ChannelConnector

MINISLACK = "http://minislack.test"

CHANNELS = [
    ("email", "email-outbox", "MINISLACK_TOKEN_EMAIL"),
    ("whatsapp", "whatsapp-outbox", "MINISLACK_TOKEN_WHATSAPP"),
    ("sms", "sms-outbox", "MINISLACK_TOKEN_SMS"),
    ("push", "push-outbox", "MINISLACK_TOKEN_PUSH"),
    ("social", "social-outbox", "MINISLACK_TOKEN_SOCIAL"),
]


def build(namespace: str, outbox: str, token_env: str) -> ChannelConnector:
    return ChannelConnector(
        base_url=MINISLACK,
        namespace=namespace,
        channel=namespace,
        outbox=outbox,
        token_env=token_env,
        rulebook=f"{namespace}_rules",
        max_body_chars=160,
    )


async def mount(connector: ChannelConnector) -> FastMCP:
    hub = FastMCP("test")
    await connector.register(hub)
    return hub


def payload(result) -> dict:
    """Unwrap a FastMCP call result into the tool's returned dict."""
    if getattr(result, "structured_content", None):
        return result.structured_content
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace,outbox,token_env", CHANNELS)
async def test_namespace_exposes_its_three_tools(namespace, outbox, token_env):
    hub = await mount(build(namespace, outbox, token_env))
    async with Client(hub) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == {
        f"{namespace}.send",
        f"{namespace}.status",
        f"{namespace}.history",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace,outbox,token_env", CHANNELS)
@respx.mock
async def test_send_uses_own_outbox_and_own_token(
    namespace, outbox, token_env, monkeypatch
):
    monkeypatch.setenv(token_env, f"msk_{namespace}_secret")
    route = respx.post(f"{MINISLACK}/api/v1/channels/{outbox}/messages").mock(
        return_value=Response(200, json={"message": {"id": 4242}})
    )

    hub = await mount(build(namespace, outbox, token_env))
    async with Client(hub) as client:
        result = await client.call_tool(f"{namespace}.send", {"text": "hello"})

    body = payload(result)
    assert body["ok"] is True
    assert body["channel"] == namespace
    assert body["message_id"] == "4242"

    assert route.called
    request = route.calls.last.request
    # The token is the point: a namespace must not borrow another's identity.
    assert request.headers["authorization"] == f"Bearer msk_{namespace}_secret"
    assert json.loads(request.content)["text"] == "hello"


@pytest.mark.asyncio
@respx.mock
async def test_missing_token_is_reported_not_raised(monkeypatch):
    monkeypatch.delenv("MINISLACK_TOKEN_SMS", raising=False)
    hub = await mount(build("sms", "sms-outbox", "MINISLACK_TOKEN_SMS"))

    async with Client(hub) as client:
        result = await client.call_tool("sms.send", {"text": "hi"})

    body = payload(result)
    assert "MINISLACK_TOKEN_SMS" in body["error"]
    # Not retryable: a missing variable will still be missing in 500ms.
    assert body["retryable"] is False


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit_is_retryable_but_bad_request_is_not(monkeypatch):
    monkeypatch.setenv("MINISLACK_TOKEN_EMAIL", "msk_email")

    respx.post(f"{MINISLACK}/api/v1/channels/email-outbox/messages").mock(
        return_value=Response(429, json={"error": "slow down"})
    )
    connector = build("email", "email-outbox", "MINISLACK_TOKEN_EMAIL")
    connector.retries = 0
    hub = await mount(connector)
    async with Client(hub) as client:
        body = payload(await client.call_tool("email.send", {"text": "hi"}))
    assert body["retryable"] is True

    respx.post(f"{MINISLACK}/api/v1/channels/email-outbox/messages").mock(
        return_value=Response(400, json={"error": "malformed"})
    )
    async with Client(hub) as client:
        body = payload(await client.call_tool("email.send", {"text": "hi"}))
    assert body["retryable"] is False


@pytest.mark.asyncio
@respx.mock
async def test_status_reports_identity_and_declares_no_policy(monkeypatch):
    monkeypatch.setenv("MINISLACK_TOKEN_WHATSAPP", "msk_wa")
    # MiniSlack answers /me flat, not nested under "user".
    respx.get(f"{MINISLACK}/api/v1/me").mock(
        return_value=Response(
            200,
            json={
                "name": "torque-whatsapp",
                "user_type": "agent",
                "rate_limit_per_minute": 600,
            },
        )
    )

    hub = await mount(build("whatsapp", "whatsapp-outbox", "MINISLACK_TOKEN_WHATSAPP"))
    async with Client(hub) as client:
        body = payload(await client.call_tool("whatsapp.status", {}))

    assert body["identity"] == "torque-whatsapp"
    assert body["user_type"] == "agent"
    assert body["rate_limit_per_minute"] == 600
    assert body["outbox"] == "whatsapp-outbox"
    assert body["token_configured"] is True
    # The hub reports limits but never enforces them. TORQUE's deterministic
    # compliance engine holds sole blocking authority, and a second enforcement
    # point could only ever disagree with the first.
    assert body["enforces_policy"] is False


@pytest.mark.asyncio
@respx.mock
async def test_history_reads_back_the_outbox(monkeypatch):
    monkeypatch.setenv("MINISLACK_TOKEN_SOCIAL", "msk_social")
    respx.get(f"{MINISLACK}/api/v1/channels/social-outbox/messages").mock(
        return_value=Response(200, json={"messages": [{"id": 1}, {"id": 2}]})
    )

    hub = await mount(build("social", "social-outbox", "MINISLACK_TOKEN_SOCIAL"))
    async with Client(hub) as client:
        body = payload(await client.call_tool("social.history", {"limit": 5}))

    assert body["count"] == 2
    assert body["outbox"] == "social-outbox"
