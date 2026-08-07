"""Marketing-channel connectors.

Five namespaces — email, whatsapp, sms, push, social — each exposing
``<namespace>.send``, ``<namespace>.status`` and ``<namespace>.history``, and
each holding its **own** MiniSlack agent token.

Why one class instantiated five times rather than five classes: the channels
differ in *configuration* (which token, which outbox, what a message costs),
not in *behaviour*. A per-channel class would be five copies of the same
twenty lines waiting to drift apart.

Why one token per namespace: MiniSlack rate-limits per token. A campaign
fanning out across five channels on a single token trips 429s partway through
and delivers a half-finished demo. Five tokens multiply the ceiling and, just
as usefully, make each channel's traffic separately attributable in the
upstream's own logs.

Why REST + Bearer rather than Socket.IO: the Socket.IO path is MiniSlack's
*human browser login*. An agent authenticates with a minted token against
``/api/v1``. Using the human path for a bot means impersonating a seat, losing
per-agent attribution, and depending on an event ordering that was designed
for a UI.

**This connector deliberately enforces no policy.** It does not check consent,
message length, template approval or any regulatory rule, even though it knows
each channel's limit and reports it in ``status``. Compliance is TORQUE's
deterministic engine and it holds sole blocking authority; a second enforcement
point here could only ever disagree with the first, and a refusal that never
reaches the audit chain is worse than no refusal at all. The hub is transport.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

from fastmcp import FastMCP

from src.core.http_client import get_client, make_error, resilient_request

logger = structlog.get_logger()


class ChannelConnector:
    """One marketing channel, fronted as an MCP namespace."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        retries: int = 2,
        *,
        namespace: str = "channel",
        channel: str = "",
        outbox: str = "",
        token_env: str = "",
        max_body_chars: int = 0,
        cost_per_message_inr: float = 0.0,
        rulebook: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        # The namespace IS the tool-name prefix: namespace "email" produces
        # email.send / email.status / email.history. Tools are registered
        # straight onto the hub with those dotted names rather than mounted as
        # a sub-server, because the caller's contract names the exact string
        # and a mount separator is FastMCP's choice, not ours.
        self.namespace = namespace
        self.channel = channel or namespace
        self.outbox = outbox
        self.token_env = token_env
        self.max_body_chars = max_body_chars
        self.cost_per_message_inr = cost_per_message_inr
        self.rulebook = rulebook
        self.name = f"channel_{channel}"

    @property
    def token(self) -> str:
        """Read the token at call time, not at construction.

        The hub starts before anyone checks whether the environment is
        complete, and a missing token should surface as a clear per-call error
        naming the variable — not as a mount failure that takes the whole
        namespace off the map.
        """
        return os.environ.get(self.token_env, "")

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def register(self, mcp: FastMCP) -> None:
        connector = self
        client = get_client(self.base_url, self.timeout)
        ns = self.namespace

        @mcp.tool(name=f"{ns}.send")
        async def send(
            text: str,
            campaign_id: str | None = None,
            variant_id: str | None = None,
        ) -> dict:
            """Deliver a rendered message to this channel's outbox.

            `campaign_id` and `variant_id` are optional provenance. They are
            already embedded in the rendered envelope by the caller; accepting
            them here too means the hub's own logs can be filtered by campaign
            without parsing message bodies.
            """
            if not connector.token:
                return make_error(
                    f"no agent token configured — set {connector.token_env}",
                    upstream="minislack",
                    retryable=False,
                )
            try:
                resp = await resilient_request(
                    client,
                    "POST",
                    f"/api/v1/channels/{connector.outbox}/messages",
                    upstream=connector.name,
                    retries=connector.retries,
                    headers=connector._auth(),
                    json={"text": text},
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                return make_error(
                    f"HTTP {status} from MiniSlack",
                    upstream="minislack",
                    # 429 is worth retrying once the minute rolls over; a 4xx
                    # that is not rate limiting means the request itself is
                    # wrong and retrying just burns budget.
                    retryable=status == 429 or status >= 500,
                )
            except Exception as exc:
                return make_error(str(exc)[:200], upstream="minislack")

            body: dict[str, Any] = resp.json()
            message_id = str(body.get("message", {}).get("id", ""))
            await logger.ainfo(
                "channel_sent",
                channel=connector.channel,
                outbox=connector.outbox,
                message_id=message_id,
                campaign_id=campaign_id,
                variant_id=variant_id,
            )
            return {
                "ok": True,
                "channel": connector.channel,
                "outbox": connector.outbox,
                "message_id": message_id,
            }

        @mcp.tool(name=f"{ns}.status")
        async def status() -> dict:
            """Report this namespace's identity, outbox and channel facts.

            Calling /me proves *which* agent this namespace authenticates as,
            which is the fastest way to catch the classic misconfiguration of
            five namespaces accidentally sharing one token.
            """
            info: dict[str, Any] = {
                "channel": connector.channel,
                "outbox": connector.outbox,
                "rulebook": connector.rulebook,
                "max_body_chars": connector.max_body_chars,
                "cost_per_message_inr": connector.cost_per_message_inr,
                "token_env": connector.token_env,
                "token_configured": bool(connector.token),
                # Limits are reported, never enforced — see the module
                # docstring. TORQUE's compliance engine is the only thing that
                # may refuse a message.
                "enforces_policy": False,
            }
            if not connector.token:
                info["identity"] = None
                info["reachable"] = False
                return info
            try:
                resp = await resilient_request(
                    client, "GET", "/api/v1/me",
                    upstream=connector.name, retries=0,
                    headers=connector._auth(),
                )
                me = resp.json()
                # MiniSlack answers /me flat: {name, user_type,
                # rate_limit_per_minute}. Other deployments nest under "user",
                # so try both rather than dumping the whole object as an
                # "identity".
                who = me.get("user", me) if isinstance(me, dict) else {}
                info["identity"] = who.get("name") or who.get("username")
                info["user_type"] = who.get("user_type")
                info["rate_limit_per_minute"] = who.get("rate_limit_per_minute")
                info["reachable"] = True
            except Exception as exc:
                info["identity"] = None
                info["reachable"] = False
                info["error"] = str(exc)[:200]
            return info

        @mcp.tool(name=f"{ns}.history")
        async def history(limit: int = 20) -> dict:
            """Read back what actually landed in this channel's outbox."""
            if not connector.token:
                return make_error(
                    f"no agent token configured — set {connector.token_env}",
                    upstream="minislack",
                    retryable=False,
                )
            try:
                resp = await resilient_request(
                    client,
                    "GET",
                    f"/api/v1/channels/{connector.outbox}/messages",
                    upstream=connector.name,
                    retries=connector.retries,
                    headers=connector._auth(),
                    params={"limit": limit},
                )
            except Exception as exc:
                return make_error(str(exc)[:200], upstream="minislack")

            payload = resp.json()
            messages = (
                payload.get("messages", payload)
                if isinstance(payload, dict)
                else payload
            )
            return {
                "channel": connector.channel,
                "outbox": connector.outbox,
                "count": len(messages),
                "messages": messages,
            }
