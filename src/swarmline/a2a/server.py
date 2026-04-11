"""A2A Server — HTTP/SSE endpoints for the A2A protocol.

Exposes a Swarmline Agent as an A2A service via Starlette ASGI app.
Uses JSON-RPC 2.0 over HTTP as per the A2A specification.

Requires: ``pip install swarmline[a2a]`` (starlette)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from swarmline.network_safety import is_loopback_host

logger = logging.getLogger(__name__)


def _try_import_starlette() -> tuple[Any, ...]:
    """Lazy import Starlette components."""
    try:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response
        from starlette.routing import Route

        return Starlette, Request, JSONResponse, Response, Route
    except ImportError:
        raise ImportError(
            "Starlette is required for A2AServer. "
            "Install it with: pip install swarmline[a2a]"
        ) from None


class A2AServer:
    """HTTP server for the A2A protocol.

    Parameters
    ----------
    adapter:
        SwarmlineA2AAdapter instance wrapping a Swarmline Agent.
    host:
        Bind host. Default: ``"0.0.0.0"``.
    port:
        Bind port. Default: ``8000``.
    """

    def __init__(
        self,
        adapter: Any,
        *,
        host: str = "127.0.0.1",
        port: int = 8000,
        auth_token: str | None = None,
        max_request_size: int = 1_048_576,
        allow_unauthenticated_local: bool = False,
    ) -> None:
        _validate_control_plane_auth(
            host=host,
            auth_token=auth_token,
            allow_unauthenticated_local=allow_unauthenticated_local,
            component="A2AServer",
        )
        self._adapter = adapter
        self._host = host
        self._port = port
        self._auth_token = auth_token
        self._max_request_size = max_request_size
        self._allow_unauthenticated_local = allow_unauthenticated_local
        self._app: Any = None

    @property
    def app(self) -> Any:
        """Get or create the Starlette ASGI application."""
        if self._app is None:
            self._app = self._create_app()
        return self._app

    def _create_app(self) -> Any:
        """Create a Starlette ASGI app with A2A routes."""
        Starlette, Request, JSONResponse, Response, Route = _try_import_starlette()

        adapter = self._adapter
        auth_token = self._auth_token
        max_request_size = self._max_request_size

        async def agent_card_endpoint(request: Any) -> Any:
            """GET /.well-known/agent.json — discovery (no auth required)."""
            card = adapter.agent_card
            return JSONResponse(card.model_dump(by_alias=True, exclude_none=True))

        async def rpc_endpoint(request: Any) -> Any:
            """POST / — JSON-RPC 2.0 dispatcher.

            Methods:
            - tasks/send: create/resume task (non-streaming)
            - tasks/sendSubscribe: create/resume task (SSE streaming)
            - tasks/get: retrieve task by ID
            - tasks/cancel: cancel a task
            """
            # Auth check — if auth_token is configured, require Bearer token
            if auth_token:
                import hmac

                auth_header = request.headers.get("authorization", "")
                if not hmac.compare_digest(auth_header, f"Bearer {auth_token}"):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)

            # Request size check — read raw body and validate length
            try:
                body_bytes = await request.body()
            except Exception:
                return _json_rpc_error(None, -32700, "Parse error")

            if len(body_bytes) > max_request_size:
                return _json_rpc_error(None, -32600, "Request too large")

            try:
                body = json.loads(body_bytes)
            except Exception:
                return _json_rpc_error(None, -32700, "Parse error")

            method = body.get("method", "")
            params = body.get("params", {})
            rpc_id = body.get("id")

            if method == "tasks/send":
                return await _handle_send(adapter, params, rpc_id, JSONResponse)
            elif method == "tasks/sendSubscribe":
                return await _handle_send_subscribe(
                    adapter, params, rpc_id, Response
                )
            elif method == "tasks/get":
                return _handle_get(adapter, params, rpc_id, JSONResponse)
            elif method == "tasks/cancel":
                return await _handle_cancel(adapter, params, rpc_id, JSONResponse)
            else:
                return _json_rpc_error(rpc_id, -32601, f"Method not found: {method}")

        routes = [
            Route("/.well-known/agent.json", agent_card_endpoint, methods=["GET"]),
            Route("/", rpc_endpoint, methods=["POST"]),
        ]

        return Starlette(routes=routes)

    async def serve(self) -> None:
        """Start the server with uvicorn.

        Requires: ``pip install uvicorn``
        """
        try:
            import uvicorn
        except ImportError:
            raise ImportError(
                "uvicorn is required to serve. Install with: pip install uvicorn"
            ) from None

        config = uvicorn.Config(
            app=self.app,
            host=self._host,
            port=self._port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()


def _validate_control_plane_auth(
    *,
    host: str,
    auth_token: str | None,
    allow_unauthenticated_local: bool,
    component: str,
) -> None:
    if auth_token:
        return
    if not allow_unauthenticated_local:
        raise ValueError(
            f"{component} requires auth_token by default. "
            "Set allow_unauthenticated_local=True only for explicit local development."
        )
    if not is_loopback_host(host):
        raise ValueError(
            f"{component} allow_unauthenticated_local=True is only allowed on loopback hosts"
        )


# ---------------------------------------------------------------------------
# RPC handlers
# ---------------------------------------------------------------------------


async def _handle_send(
    adapter: Any, params: dict[str, Any], rpc_id: Any, JSONResponse: Any
) -> Any:
    """Handle tasks/send — synchronous task execution."""

    task_data = params.get("task") or params
    task = _build_task(task_data)

    result_task = await adapter.handle_task(task)

    return JSONResponse(
        _json_rpc_result(rpc_id, result_task.model_dump(by_alias=True, exclude_none=True))
    )


async def _handle_send_subscribe(
    adapter: Any, params: dict[str, Any], rpc_id: Any, Response: Any
) -> Any:
    """Handle tasks/sendSubscribe — SSE streaming."""

    task_data = params.get("task") or params
    task = _build_task(task_data)

    async def event_generator() -> Any:
        async for event in adapter.handle_task_streaming(task):
            data = event.model_dump(by_alias=True, exclude_none=True)
            sse_line = f"data: {json.dumps(data)}\n\n"
            yield sse_line.encode("utf-8")

    from starlette.responses import StreamingResponse

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _handle_get(
    adapter: Any, params: dict[str, Any], rpc_id: Any, JSONResponse: Any
) -> Any:
    """Handle tasks/get — retrieve task by ID."""
    task_id = params.get("id") or params.get("task_id", "")
    task = adapter.get_task(task_id)

    if task is None:
        return JSONResponse(
            _json_rpc_error_body(rpc_id, -32602, f"Task not found: {task_id}")
        )

    return JSONResponse(
        _json_rpc_result(rpc_id, task.model_dump(by_alias=True, exclude_none=True))
    )


async def _handle_cancel(
    adapter: Any, params: dict[str, Any], rpc_id: Any, JSONResponse: Any
) -> Any:
    """Handle tasks/cancel — cancel a task."""
    task_id = params.get("id") or params.get("task_id", "")
    task = await adapter.cancel_task(task_id)

    if task is None:
        return JSONResponse(
            _json_rpc_error_body(rpc_id, -32602, f"Task not found: {task_id}")
        )

    return JSONResponse(
        _json_rpc_result(rpc_id, task.model_dump(by_alias=True, exclude_none=True))
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_task(task_data: dict[str, Any]) -> Any:
    """Build a Task from raw dict, handling message shorthand."""
    from swarmline.a2a.types import Message, Task, TextPart

    if "messages" in task_data:
        return Task(**task_data)

    # Shorthand: {"id": ..., "message": "text"} → Task with one user message
    msg_text = task_data.pop("message", None)
    if msg_text:
        task_data["messages"] = [
            Message(role="user", parts=[TextPart(text=msg_text)]).model_dump()
        ]
    return Task(**task_data)


def _json_rpc_result(rpc_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _json_rpc_error_body(rpc_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    }


def _json_rpc_error(rpc_id: Any, code: int, message: str) -> Any:
    """Create a JSONResponse with JSON-RPC error."""
    _, _, JSONResponse, _, _ = _try_import_starlette()
    return JSONResponse(_json_rpc_error_body(rpc_id, code, message))
