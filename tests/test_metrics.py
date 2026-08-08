"""The /metrics contract.

Asserts what would actually break the observability story if it regressed:
the endpoint exists, lists every family this hub promises, and — the part
that bit the /health route once already (BearerTokenMiddleware existed for a
release before it was ever wired in) — that a request with no token still
gets through, because a Prometheus scrape target has no way to carry one.
"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route
from starlette.testclient import TestClient

from src.core.auth import BearerTokenMiddleware
from src.core.metrics import CHANNEL_SENDS, UPSTREAM_CALLS, metrics_endpoint

FAMILIES = [
    "mcphub_upstream_calls_total",
    "mcphub_upstream_call_duration_seconds",
    "mcphub_channel_sends_total",
]


def _app_with_auth(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")
    return Starlette(
        routes=[Route("/metrics", metrics_endpoint, methods=["GET"])],
        middleware=[Middleware(BearerTokenMiddleware)],
    )


def test_metrics_lists_every_family(monkeypatch):
    client = TestClient(_app_with_auth(monkeypatch))
    r = client.get("/metrics")
    assert r.status_code == 200
    for family in FAMILIES:
        assert family in r.text, f"{family} never registered"


def test_metrics_is_reachable_without_a_bearer_token(monkeypatch):
    """A scraper carries no MCP_AUTH_TOKEN. If this 401s, Prometheus shows the
    target permanently down and every dashboard built on it goes blank."""
    client = TestClient(_app_with_auth(monkeypatch))
    r = client.get("/metrics")
    assert r.status_code == 200


def test_other_routes_still_require_the_token(monkeypatch):
    """The exemption is scoped to /health and /metrics specifically — it must
    not have accidentally disabled auth everywhere."""
    app = Starlette(
        routes=[
            Route("/metrics", metrics_endpoint, methods=["GET"]),
            Route("/mcp", metrics_endpoint, methods=["GET"]),  # stand-in
        ],
        middleware=[Middleware(BearerTokenMiddleware)],
    )
    monkeypatch.setenv("MCP_AUTH_TOKEN", "secret-token")
    client = TestClient(app)
    assert client.get("/mcp").status_code == 401
    assert client.get("/mcp", headers={"Authorization": "Bearer secret-token"}).status_code == 200


def test_channel_send_counter_records_outcome():
    before = CHANNEL_SENDS.labels(channel="email", outcome="ok")._value.get()
    CHANNEL_SENDS.labels(channel="email", outcome="ok").inc()
    after = CHANNEL_SENDS.labels(channel="email", outcome="ok")._value.get()
    assert after == before + 1
