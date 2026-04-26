"""Starlette ASGI app factory for swarmline serve."""

from __future__ import annotations

import structlog
import time
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from swarmline.network_safety import is_loopback_host
from swarmline.observability.redaction import redact_secrets
from swarmline.observability.security import log_security_decision

_VERSION = "1.5.1"
_log = structlog.get_logger(component="serve")


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
                log_security_decision(
                    _log,
                    component="serve",
                    event_name="security.http_query_denied",
                    reason="missing_or_invalid_bearer_token",
                    route=scope["path"],
                    target="query",
                )
                response = JSONResponse(
                    {"error": "Unauthorized", "ok": False},
                    status_code=401,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class _QueryClosedMiddleware:
    """Log closed query endpoint attempts while preserving a 404 response."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"] == "/v1/query":
            log_security_decision(
                _log,
                component="serve",
                event_name="security.http_query_denied",
                reason="query_disabled",
                route=scope["path"],
                target="query",
            )
            response = Response(status_code=404)
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


def _make_info_handler(endpoints: list[str]) -> Any:
    async def info(request: Request) -> Response:
        return JSONResponse(
            {
                "name": "swarmline",
                "version": _VERSION,
                "endpoints": endpoints,
            }
        )

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
            return JSONResponse(
                {
                    "text": result.text,
                    "ok": result.ok,
                    "error": result.error,
                }
            )
        except Exception as exc:
            return JSONResponse(
                {"error": redact_secrets(str(exc)), "ok": False},
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
    allow_unauthenticated_query: bool = False,
    cors_origins: list[str] | None = None,
    host: str | None = None,
) -> Starlette:
    """Create a Starlette ASGI app serving the given agent.

    When ``allow_unauthenticated_query=True`` and ``host`` is provided, the host
    must be a loopback address (``localhost`` / ``127.0.0.1`` / ``::1``).
    Mirrors the loopback gates in ``a2a/server.py`` and ``daemon/health.py``:
    the unauthenticated control plane is local-only by design.

    For backward compatibility, ``host=None`` (the v1.4.x signature) is still
    accepted but logs a security warning so operators can audit unauthenticated
    surface area.
    """
    if allow_unauthenticated_query and auth_token is None:
        # v1.5.1: the v1.5.0 deprecation warning for host=None has graduated
        # to a hard ValueError (audit P2 #5). Without this gate, an operator
        # could combine the legacy signature with `uvicorn --host 0.0.0.0`
        # and silently expose unauthenticated /v1/query publicly.
        if not host:
            raise ValueError(
                "serve.create_app(allow_unauthenticated_query=True) requires an "
                "explicit host= argument since v1.5.1. Pass host='127.0.0.1' "
                "(or another loopback) for local-only mode, or pass auth_token= "
                "for production."
            )
        if not is_loopback_host(host):
            raise ValueError(
                "serve.create_app(allow_unauthenticated_query=True) is only "
                "allowed on loopback hosts (localhost / 127.0.0.1 / ::1). "
                f"Refused host={host!r}. Pass auth_token= or bind to a "
                "loopback host."
            )

    query_enabled = auth_token is not None or allow_unauthenticated_query

    routes = [
        Route("/v1/health", _make_health_handler(), methods=["GET"]),
    ]
    endpoints = ["/v1/stream", "/v1/health", "/v1/info"]
    if query_enabled:
        routes.append(Route("/v1/query", _make_query_handler(agent), methods=["POST"]))
        endpoints.insert(0, "/v1/query")
    routes.insert(1, Route("/v1/info", _make_info_handler(endpoints), methods=["GET"]))

    middleware: list[Middleware] = []
    if not query_enabled:
        middleware.append(Middleware(_QueryClosedMiddleware))
    if auth_token:
        middleware.append(Middleware(_BearerAuthMiddleware, token=auth_token))

    return Starlette(routes=routes, middleware=middleware)
