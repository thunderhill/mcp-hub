# Task: Build "mcp-hub" — a production-grade, extensible MCP server (hackathon project)

## Context

I need an independent, network-hosted MCP server that AI agents (Claude, LangGraph,
custom clients) connect to over the network. It fronts three existing internal
services and must be trivially extensible when new services appear.

Services already running in the network:
1. **MiniSlack** (Slack-like chat) at `http://minislack:9001` — REST endpoints:
   POST /messages {channel, text}, GET /messages?channel=X, GET /channels
2. **Observability service** at `http://observability:9002` — REST endpoints:
   GET /metrics?service=X&window=5m, GET /alerts, GET /services
3. **Enterprise RAG** (FastAPI) at `http://rag:9003` — full OpenAPI spec at
   `http://rag:9003/openapi.json`; key endpoint: POST /query {question, top_k}

If an endpoint above is wrong, check the service's /docs or /openapi.json first,
then adapt — do not hardcode assumptions silently; log a warning instead.

## Hard requirements

1. **Framework:** Python 3.12, FastMCP v3 standalone package (`fastmcp`, install
   via `uv add fastmcp`). Do NOT use `mcp.server.fastmcp`.
2. **Transport:** Streamable HTTP at `/mcp`, `stateless_http=True`, host 0.0.0.0,
   port from env `MCP_PORT` (default 8000). Plus a plain `/health` endpoint.
3. **Connector architecture (the critical part):**
   - `config/services.yaml` is the service registry:
     ```yaml
     services:
       - name: minislack
         namespace: slack
         type: rest           # hand-written connector
         base_url: http://minislack:9001
         enabled: true
       - name: rag
         namespace: rag
         type: openapi        # auto-generated from OpenAPI spec
         base_url: http://rag:9003
         enabled: true
     ```
   - `src/connectors/base.py` defines a `Connector` protocol:
     `name`, `namespace`, `async register(mcp: FastMCP) -> None`.
   - `src/core/registry.py` loads services.yaml, imports the matching connector
     module (or builds one from OpenAPI for `type: openapi`), mounts each as a
     namespaced sub-server via FastMCP mounting so tools appear as
     `slack.send_message`, `obs.get_metrics`, `rag.query`.
   - Adding a future service = one new file in `src/connectors/` + one YAML
     entry. Include `src/connectors/template.py` as a documented copy-paste
     starting point.
4. **RAG connector:** use FastMCP v3's OpenAPI provider to auto-generate tools
   from `http://rag:9003/openapi.json` at startup. If the spec is unreachable,
   log the failure and continue serving the other connectors (graceful
   degradation — one dead upstream must never crash the hub).
5. **Resilience:** shared `httpx.AsyncClient` with per-upstream timeout (5s),
   2 retries with backoff; every tool catches upstream errors and returns a
   structured error object `{"error": "...", "upstream": "...", "retryable": true}`
   — never leak stack traces to the agent.
6. **Validation:** validate every tool argument (Pydantic); reject empty channel
   names, negative top_k, etc.
7. **Auth:** bearer-token middleware on `/mcp` — token from env `MCP_AUTH_TOKEN`;
   requests without `Authorization: Bearer <token>` get 401. `/health` stays open.
8. **Observability:** structured JSON logs (structlog or stdlib json formatter);
   for every tool call log: tool name, namespace, latency_ms, status,
   upstream, error type (never log full argument values — log arg keys only).
9. **Tests:** pytest with FastMCP's in-memory Client — one test file per
   connector mocking the upstream with respx or httpx MockTransport, plus a
   registry test proving all enabled services mount correctly.
10. **Docker:** multi-stage Dockerfile (python:3.12-slim, non-root user, uv for
    deps, HEALTHCHECK on /health) and docker-compose.yaml with the hub plus
    stub implementations of the three services (tiny FastAPI stubs) so the whole
    demo runs offline.

## Deliverables (in order)
1. Project scaffold + dependency setup that runs: `uv run python -m src.main`
   serves /mcp and /health.
2. `slack.*` and `obs.*` connectors with tests.
3. OpenAPI-driven `rag.*` connector with graceful-degradation test.
4. Auth, logging, Dockerfile, docker-compose.
5. `demo_client.py`: a script that connects with FastMCP Client, lists all
   tools, then chains rag.query → slack.send_message → obs.get_metrics to prove
   end-to-end agent flow.

Build incrementally in that order, running tests after each step. Ask me for
the real endpoint specs only if you cannot proceed with the ones above.
