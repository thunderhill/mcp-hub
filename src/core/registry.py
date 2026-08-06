from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
import structlog

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.connectors.slack import SlackConnector
from src.connectors.observability import ObservabilityConnector
from src.connectors.rag import RagConnector

logger = structlog.get_logger()

CONNECTOR_MAP: dict[str, type] = {
    "minislack": SlackConnector,
    "observability": ObservabilityConnector,
    "rag": RagConnector,
}

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "services.yaml"


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

    services = load_service_config(config_path)

    for svc in services:
        if not svc.get("enabled", True):
            await logger.ainfo("service_disabled", name=svc["name"])
            continue

        name = svc["name"]
        namespace = svc.get("namespace", name)
        base_url = svc["base_url"]
        timeout = svc.get("timeout", 5.0)
        retries = svc.get("retries", 2)

        connector_cls = CONNECTOR_MAP.get(name)
        if connector_cls is None:
            await logger.awarning("no_connector_found", name=name)
            continue

        try:
            sub = FastMCP(namespace)
            connector = connector_cls(
                base_url=base_url,
                timeout=timeout,
                retries=retries,
            )
            await connector.register(sub)
            hub.mount(sub, namespace=namespace)
            await logger.ainfo(
                "service_mounted",
                name=name,
                namespace=namespace,
                base_url=base_url,
            )
        except Exception as exc:
            await logger.aerror(
                "service_mount_failed",
                name=name,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    return hub
