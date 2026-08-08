from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
import structlog

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.connectors.channels import ChannelConnector
from src.connectors.slack import SlackConnector
from src.connectors.observability import ObservabilityConnector
from src.connectors.rag import RagConnector
from src.core.metrics import metrics_endpoint

logger = structlog.get_logger()

# Keyed by the service's `connector:` field, falling back to `name:` so the
# original single-instance services keep working unchanged. The channel
# connector is one class serving five namespaces, which is why it cannot be
# keyed by service name.
CONNECTOR_MAP: dict[str, type] = {
    "channel": ChannelConnector,
    "minislack": SlackConnector,
    "observability": ObservabilityConnector,
    "rag": RagConnector,
}

# Connectors that own their full dotted tool names and are registered straight
# onto the hub. Everything else is mounted as a namespaced sub-server.
SELF_NAMESPACED = {"channel"}

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "services.yaml"

_ENV_REF = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def expand_env(value: Any) -> Any:
    """Resolve ``${VAR}`` and ``${VAR:-default}`` inside config strings.

    The four units migrate to separate laptops, so a base_url must never be
    baked into a file that is committed. Interpolating from the environment
    keeps services.yaml describing *topology* while the addresses stay
    deployment-specific.
    """
    if not isinstance(value, str):
        return value

    def sub(m: re.Match[str]) -> str:
        return os.environ.get(m.group(1)) or (m.group(2) or "")

    return _ENV_REF.sub(sub, value)


def load_service_config(path: Path | None = None) -> list[dict[str, Any]]:
    config_path = path or CONFIG_PATH
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data.get("services", [])


async def build_hub(
    config_path: Path | None = None,
) -> FastMCP:
    hub = FastMCP("mcp-hub")

    @hub.custom_route("/health", methods=["GET"])
    async def health_check(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    hub.custom_route("/metrics", methods=["GET"])(metrics_endpoint)

    services = load_service_config(config_path)

    for svc in services:
        if not svc.get("enabled", True):
            await logger.ainfo("service_disabled", name=svc["name"])
            continue

        name = svc["name"]
        namespace = svc.get("namespace", name)
        base_url = expand_env(svc["base_url"])
        timeout = svc.get("timeout", 5.0)
        retries = svc.get("retries", 2)
        kind = svc.get("connector", name)

        connector_cls = CONNECTOR_MAP.get(kind)
        if connector_cls is None:
            await logger.awarning("no_connector_found", name=name, connector=kind)
            continue

        options = {k: expand_env(v) for k, v in (svc.get("options") or {}).items()}

        try:
            connector = connector_cls(
                base_url=base_url,
                timeout=timeout,
                retries=retries,
                **({"namespace": namespace, **options} if kind in SELF_NAMESPACED else options),
            )

            if kind in SELF_NAMESPACED:
                await connector.register(hub)
            else:
                sub = FastMCP(namespace)
                await connector.register(sub)
                hub.mount(sub, namespace=namespace)

            await logger.ainfo(
                "service_mounted",
                name=name,
                namespace=namespace,
                base_url=base_url,
            )
        except Exception as exc:
            # One misconfigured service must never take the hub down with it.
            # A campaign that loses SMS should still deliver email.
            await logger.aerror(
                "service_mount_failed",
                name=name,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    # Log the resolved tool names at startup. Worth the line: the contract
    # between TORQUE and the hub is a set of literal strings ("email.send"),
    # and a mismatch is otherwise invisible until a campaign silently fails to
    # deliver.
    tools = await hub.list_tools()
    await logger.ainfo("hub_ready", tools=sorted(t.name for t in tools))
    return hub
