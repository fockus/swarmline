"""Starlette ASGI app factory for cognitia serve."""

from __future__ import annotations

import time
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


_VERSION = "1.1.0"


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


class _BearerAuthMiddleware:
    """Optional Bearer token authentication. Health/info endpoints are exempt."""

    EXEMPT_PATHS = {"/v1/health", "/v1/info"}

    def __init__(self, app: Any, *, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"] not in self.EXEMPT_PATHS:
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            if auth != f"Bearer {self.token}":
                response = JSONResponse(
                    {"error": "Unauthorized", "ok": False},
                    status_code=401,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


def _make_health_handler() -> Any:
    async def health(request: Request) -> Response:
        return JSONResponse({"status": "ok", "timestamp": time.time()})
    return health


def _make_info_handler() -> Any:
    async def info(request: Request) -> Response:
        return JSONResponse({
            "name": "cognitia",
            "version": _VERSION,
            "endpoints": ["/v1/query", "/v1/stream", "/v1/health", "/v1/info"],
        })
    return info


def _make_query_handler(agent: Any) -> Any:
    async def query(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON", "ok": False}, status_code=400)

        prompt = body.get("prompt", "")
        if not prompt:
            return JSONResponse(
                {"error": "Missing or empty 'prompt' field", "ok": False},
                status_code=400,
            )

        try:
            result = await agent.query(prompt)
            return JSONResponse({
                "text": result.text,
                "ok": result.ok,
                "error": result.error,
            })
        except Exception as exc:
            return JSONResponse(
                {"error": str(exc), "ok": False},
                status_code=500,
            )

    return query


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    agent: Any,
    *,
    auth_token: str | None = None,
    cors_origins: list[str] | None = None,
) -> Starlette:
    """Create a Starlette ASGI app serving the given agent."""
    routes = [
        Route("/v1/health", _make_health_handler(), methods=["GET"]),
        Route("/v1/info", _make_info_handler(), methods=["GET"]),
        Route("/v1/query", _make_query_handler(agent), methods=["POST"]),
    ]

    middleware: list[Middleware] = []
    if auth_token:
        middleware.append(Middleware(_BearerAuthMiddleware, token=auth_token))

    return Starlette(routes=routes, middleware=middleware)
