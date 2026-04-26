"""Minimal async HTTP health server — stdlib only, no aiohttp."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable

import structlog

from swarmline.network_safety import is_loopback_host

logger = structlog.get_logger(component="daemon.health")

# Maximum request size (prevent DoS)
_MAX_REQUEST_SIZE = 8192
# Read timeout to prevent slow-loris attacks
_READ_TIMEOUT_SECONDS = 10.0


class HealthServer:
    """Async HTTP health endpoint using ``asyncio.start_server``.

    Implements ``HealthEndpoint`` protocol.

    Endpoints:
        GET  /health  → ``{"status": "ok", "uptime": <seconds>}``
        GET  /status  → full daemon status JSON (via status_provider)
        POST /pause   → call on_pause, return result  *(requires auth_token if set)*
        POST /resume  → call on_resume, return result  *(requires auth_token if set)*

    Security:
        If ``auth_token`` is provided, mutating endpoints (POST /pause,
        POST /resume) require ``Authorization: Bearer <token>`` header.
        Read endpoints (GET /health, GET /status) are always open.

    Usage::

        server = HealthServer(
            port=8471,
            status_provider=daemon.get_status,
            on_pause=daemon.pause,
            on_resume=daemon.resume,
            auth_token="<your-secret-token>",
        )
        await server.start()
        ...
        await server.stop()
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8471,
        *,
        status_provider: Callable[[], dict[str, Any]] | None = None,
        on_pause: Callable[[], Any] | None = None,
        on_resume: Callable[[], Any] | None = None,
        auth_token: str | None = None,
        allow_unauthenticated_local: bool = False,
    ) -> None:
        if auth_token is None:
            if not allow_unauthenticated_local:
                raise ValueError(
                    "HealthServer requires auth_token by default. "
                    "Set allow_unauthenticated_local=True only for explicit local development."
                )
            if not is_loopback_host(host):
                raise ValueError(
                    "HealthServer allow_unauthenticated_local=True is only allowed on loopback hosts"
                )
        self._host = host
        self._port = port
        self._status_provider = status_provider
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._auth_token = auth_token
        self._allow_unauthenticated_local = allow_unauthenticated_local
        self._server: asyncio.Server | None = None
        self._started_at: float = 0.0

    async def start(self) -> None:
        """Start TCP server."""
        self._started_at = time.monotonic()
        self._server = await asyncio.start_server(
            self._handle_connection,
            self._host,
            self._port,
        )
        logger.info("health.started", host=self._host, port=self._port)

    async def stop(self) -> None:
        """Stop server gracefully."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("health.stopped")

    @property
    def is_running(self) -> bool:
        """Whether server is currently serving."""
        return self._server is not None and self._server.is_serving()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single HTTP connection with read timeout."""
        try:
            try:
                data = await asyncio.wait_for(
                    reader.read(_MAX_REQUEST_SIZE),
                    timeout=_READ_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                writer.write(_build_response(408, {"error": "Request Timeout"}))
                await writer.drain()
                return

            if not data:
                return

            method, path, headers = _parse_request(data)

            # Auth check for mutating endpoints
            if self._auth_token and path in {"/pause", "/resume"}:
                import hmac

                auth = headers.get("authorization", "")
                if not hmac.compare_digest(auth, f"Bearer {self._auth_token}"):
                    writer.write(_build_response(401, {"error": "Unauthorized"}))
                    await writer.drain()
                    return

            status, body = self._route(method, path)
            response = _build_response(status, body)
            writer.write(response)
            await writer.drain()
        except Exception:
            logger.warning("health.request.error", exc_info=True)
            try:
                writer.write(_build_response(500, {"error": "Internal Server Error"}))
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _route(self, method: str, path: str) -> tuple[int, dict[str, Any]]:
        """Route request to handler. Returns (status_code, body_dict)."""
        if method == "GET" and path == "/health":
            return self._handle_health()
        if method == "GET" and path == "/status":
            return self._handle_status()
        if method == "POST" and path == "/pause":
            return self._handle_pause()
        if method == "POST" and path == "/resume":
            return self._handle_resume()

        # Method check for known paths
        known_paths = {"/health", "/status", "/pause", "/resume"}
        if path in known_paths:
            return 405, {"error": "Method Not Allowed"}

        return 404, {"error": "Not Found"}

    def _handle_health(self) -> tuple[int, dict[str, Any]]:
        uptime = time.monotonic() - self._started_at
        return 200, {"status": "ok", "uptime_seconds": round(uptime, 1)}

    def _handle_status(self) -> tuple[int, dict[str, Any]]:
        if self._status_provider is None:
            return 200, {"status": "ok", "detail": "no status provider configured"}
        return 200, self._status_provider()

    def _handle_pause(self) -> tuple[int, dict[str, Any]]:
        if self._on_pause is not None:
            self._on_pause()
        return 200, {"status": "paused"}

    def _handle_resume(self) -> tuple[int, dict[str, Any]]:
        if self._on_resume is not None:
            self._on_resume()
        return 200, {"status": "resumed"}


def _parse_request(data: bytes) -> tuple[str, str, dict[str, str]]:
    """Parse HTTP request. Returns (method, path, headers_dict)."""
    lines = data.split(b"\r\n")
    headers: dict[str, str] = {}

    # Parse request line
    try:
        request_line = lines[0].decode("ascii")
    except (UnicodeDecodeError, IndexError):
        return "GET", "/", headers

    parts = request_line.split(" ")
    if len(parts) < 2:
        return "GET", "/", headers

    method = parts[0].upper()
    path = parts[1].split("?", 1)[0]  # Strip query string

    # Parse headers
    for line in lines[1:]:
        if not line:
            break
        try:
            decoded = line.decode("ascii")
        except UnicodeDecodeError:
            continue
        if ":" in decoded:
            key, _, value = decoded.partition(":")
            headers[key.strip().lower()] = value.strip()

    return method, path, headers


def _build_response(status: int, body: dict[str, Any]) -> bytes:
    """Build minimal HTTP/1.1 response."""
    status_text = {
        200: "OK",
        401: "Unauthorized",
        404: "Not Found",
        405: "Method Not Allowed",
        408: "Request Timeout",
        500: "Internal Server Error",
    }.get(status, "Unknown")

    body_bytes = json.dumps(body).encode("utf-8")
    header = (
        f"HTTP/1.1 {status} {status_text}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )
    return header.encode("ascii") + body_bytes
