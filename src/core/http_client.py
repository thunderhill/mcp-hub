from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import structlog

from src.core.metrics import UPSTREAM_CALL_DURATION, UPSTREAM_CALLS

logger = structlog.get_logger()

_clients: dict[str, httpx.AsyncClient] = {}


def get_client(
    base_url: str,
    timeout: float = 5.0,
) -> httpx.AsyncClient:
    if base_url not in _clients:
        _clients[base_url] = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout),
        )
    return _clients[base_url]


async def close_all() -> None:
    for client in _clients.values():
        await client.aclose()
    _clients.clear()


async def resilient_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    upstream: str,
    retries: int = 2,
    **kwargs: Any,
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 2):
        start = time.monotonic()
        try:
            resp = await client.request(method, path, **kwargs)
            resp.raise_for_status()
            elapsed = time.monotonic() - start
            latency = elapsed * 1000
            UPSTREAM_CALLS.labels(upstream=upstream, method=method, outcome="success").inc()
            UPSTREAM_CALL_DURATION.labels(upstream=upstream, method=method).observe(elapsed)
            await logger.ainfo(
                "upstream_call",
                upstream=upstream,
                method=method,
                path=path,
                status=resp.status_code,
                latency_ms=round(latency, 2),
                attempt=attempt,
            )
            return resp
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            last_exc = exc
            elapsed = time.monotonic() - start
            latency = elapsed * 1000
            UPSTREAM_CALLS.labels(upstream=upstream, method=method, outcome="error").inc()
            UPSTREAM_CALL_DURATION.labels(upstream=upstream, method=method).observe(elapsed)
            await logger.awarning(
                "upstream_call_failed",
                upstream=upstream,
                method=method,
                path=path,
                attempt=attempt,
                latency_ms=round(latency, 2),
                error_type=type(exc).__name__,
            )
            if attempt <= retries:
                await asyncio.sleep(0.5 * attempt)
    raise last_exc  # type: ignore[misc]


def make_error(
    error: str,
    upstream: str,
    retryable: bool = True,
) -> dict[str, Any]:
    return {"error": error, "upstream": upstream, "retryable": retryable}
