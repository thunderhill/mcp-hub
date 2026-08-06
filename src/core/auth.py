from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class BearerTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        token = os.environ.get("MCP_AUTH_TOKEN")
        if token:
            auth_header = request.headers.get("authorization", "")
            if auth_header != f"Bearer {token}":
                return JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                )

        return await call_next(request)
