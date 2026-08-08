"""Prometheus instrumentation.

One generic pair covers every connector uniformly: `resilient_request` in
`http_client.py` is the single choke point every upstream call already passes
through (channels, slack, observability's own Grafana calls once it is
enabled), so instrumenting it there means a new connector is metered for
free, with no per-connector wiring to remember.

`channel_sends_total` sits at a higher level, split by marketing channel
rather than by HTTP path — "how many WhatsApp sends succeeded" is a different
question from "how many POSTs to /channels/whatsapp-outbox/messages
succeeded", and TORQUE's delivery client cares about the former.

`/metrics` is exempt from `BearerTokenMiddleware`, matching `/health` — a
Prometheus scrape target should not need a token that rotates independently
of the scrape config.
"""
from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

UPSTREAM_CALLS = Counter(
    "mcphub_upstream_calls_total",
    "Calls to an upstream service, by name and outcome",
    ["upstream", "method", "outcome"],  # outcome: success | error
)

UPSTREAM_CALL_DURATION = Histogram(
    "mcphub_upstream_call_duration_seconds",
    "Upstream call latency, by name and method",
    ["upstream", "method"],
)

CHANNEL_SENDS = Counter(
    "mcphub_channel_sends_total",
    "Marketing-channel sends, by channel and outcome",
    ["channel", "outcome"],  # outcome: ok | failed
)


async def metrics_endpoint(request: Request) -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
