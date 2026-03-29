"""A2A Server — HTTP/SSE endpoints for the A2A protocol.

Exposes a Cognitia Agent as an A2A service via Starlette ASGI app.
Uses JSON-RPC 2.0 over HTTP as per the A2A specification.

Requires: ``pip install cognitia[a2a]`` (starlette)
"""

from __future__ import annotations

import json
import logging
from typing import Any

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
            "Install it with: pip install cognitia[a2a]"
        ) from None


class A2AServer:
    """HTTP server for the A2A protocol.

    Parameters
    ----------
    adapter:
        CognitiaA2AAdapter instance wrapping a Cognitia Agent.
    host:
        Bind host. Default: ``"0.0.0.0"``.
    port:
        Bind port. Default: ``8000``.
    """

    def __init__(
        self,
        adapter: Any,
        *,
        host: str = "0.0.0.0",
        port: int = 8000,
    ) -> None:
        self._adapter = adapter
        self._host = host
        self._port = port
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

        async def agent_card_endpoint(request: Any) -> Any:
            """GET /.well-known/agent.json — discovery."""
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
            try:
                body = await request.json()
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
    from cognitia.a2a.types import Message, Task, TextPart

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
