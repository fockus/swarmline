"""Unit tests for HealthServer."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from swarmline.daemon.health import HealthServer, _build_response, _parse_request


class TestParseRequest:

    def test_get_health(self) -> None:
        data = b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n"
        method, path, headers = _parse_request(data)
        assert method == "GET"
        assert path == "/health"
        assert headers["host"] == "localhost"

    def test_post_pause(self) -> None:
        data = b"POST /pause HTTP/1.1\r\n\r\n"
        method, path, _ = _parse_request(data)
        assert method == "POST"
        assert path == "/pause"

    def test_strips_query_string(self) -> None:
        data = b"GET /status?format=json HTTP/1.1\r\n\r\n"
        method, path, _ = _parse_request(data)
        assert path == "/status"

    def test_empty_data(self) -> None:
        method, path, _ = _parse_request(b"")
        assert method == "GET"
        assert path == "/"

    def test_authorization_header(self) -> None:
        data = b"POST /pause HTTP/1.1\r\nAuthorization: Bearer secret123\r\n\r\n"
        _, _, headers = _parse_request(data)
        assert headers["authorization"] == "Bearer secret123"


class TestBuildResponse:

    def test_200_ok(self) -> None:
        resp = _build_response(200, {"status": "ok"})
        assert b"HTTP/1.1 200 OK\r\n" in resp
        assert b"Content-Type: application/json\r\n" in resp
        body = resp.split(b"\r\n\r\n", 1)[1]
        data = json.loads(body)
        assert data["status"] == "ok"

    def test_404(self) -> None:
        resp = _build_response(404, {"error": "Not Found"})
        assert b"HTTP/1.1 404 Not Found\r\n" in resp

    def test_401(self) -> None:
        resp = _build_response(401, {"error": "Unauthorized"})
        assert b"HTTP/1.1 401 Unauthorized\r\n" in resp


class TestHealthServer:

    @pytest.fixture()
    async def server_and_port(self):
        """Start a HealthServer on ephemeral port."""
        state: dict[str, Any] = {"paused": False}

        def status_provider() -> dict[str, Any]:
            return {"state": "running", "tasks": 5}

        def on_pause() -> None:
            state["paused"] = True

        def on_resume() -> None:
            state["paused"] = False

        srv = HealthServer(
            host="127.0.0.1",
            port=0,
            status_provider=status_provider,
            on_pause=on_pause,
            on_resume=on_resume,
            allow_unauthenticated_local=True,
        )
        await srv.start()
        port = srv._server.sockets[0].getsockname()[1]

        yield srv, port, state

        await srv.stop()

    async def _request(
        self, port: int, method: str, path: str,
        *, headers: dict[str, str] | None = None,
    ) -> tuple[int, dict]:
        """Send a raw HTTP request and parse response."""
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        hdr_lines = ""
        if headers:
            for k, v in headers.items():
                hdr_lines += f"{k}: {v}\r\n"
        request = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n{hdr_lines}\r\n"
        writer.write(request.encode())
        await writer.drain()

        data = await reader.read(4096)
        writer.close()
        await writer.wait_closed()

        status_line = data.split(b"\r\n", 1)[0].decode()
        status_code = int(status_line.split(" ", 2)[1])
        body = data.split(b"\r\n\r\n", 1)[1]
        return status_code, json.loads(body)

    async def test_health_endpoint(self, server_and_port) -> None:
        srv, port, _ = server_and_port
        status, body = await self._request(port, "GET", "/health")
        assert status == 200
        assert body["status"] == "ok"
        assert "uptime_seconds" in body

    async def test_status_endpoint(self, server_and_port) -> None:
        srv, port, _ = server_and_port
        status, body = await self._request(port, "GET", "/status")
        assert status == 200
        assert body["state"] == "running"
        assert body["tasks"] == 5

    async def test_pause_endpoint(self, server_and_port) -> None:
        srv, port, state = server_and_port
        assert state["paused"] is False
        status, body = await self._request(port, "POST", "/pause")
        assert status == 200
        assert body["status"] == "paused"
        assert state["paused"] is True

    async def test_resume_endpoint(self, server_and_port) -> None:
        srv, port, state = server_and_port
        state["paused"] = True
        status, body = await self._request(port, "POST", "/resume")
        assert status == 200
        assert body["status"] == "resumed"
        assert state["paused"] is False

    async def test_404_unknown_path(self, server_and_port) -> None:
        srv, port, _ = server_and_port
        status, body = await self._request(port, "GET", "/unknown")
        assert status == 404

    async def test_405_wrong_method(self, server_and_port) -> None:
        srv, port, _ = server_and_port
        status, body = await self._request(port, "POST", "/health")
        assert status == 405

    async def test_is_running(self, server_and_port) -> None:
        srv, port, _ = server_and_port
        assert srv.is_running is True

    async def test_is_not_running_after_stop(self) -> None:
        srv = HealthServer(port=0, allow_unauthenticated_local=True)
        assert srv.is_running is False

    async def test_no_status_provider(self) -> None:
        srv = HealthServer(port=0, allow_unauthenticated_local=True)
        await srv.start()
        port = srv._server.sockets[0].getsockname()[1]

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /status HTTP/1.1\r\n\r\n")
        await writer.drain()
        data = await reader.read(4096)
        writer.close()
        await writer.wait_closed()

        body = json.loads(data.split(b"\r\n\r\n", 1)[1])
        assert body["status"] == "ok"

        await srv.stop()

    def test_protocol_compliance(self) -> None:
        from swarmline.daemon.protocols import HealthEndpoint
        srv = HealthServer(allow_unauthenticated_local=True)
        assert isinstance(srv, HealthEndpoint)


class TestHealthServerAuth:

    @pytest.fixture()
    async def auth_server(self):
        """Start a HealthServer with auth token."""
        srv = HealthServer(
            host="127.0.0.1",
            port=0,
            on_pause=lambda: None,
            on_resume=lambda: None,
            auth_token="test-secret",
        )
        await srv.start()
        port = srv._server.sockets[0].getsockname()[1]
        yield srv, port
        await srv.stop()

    async def _request(
        self, port: int, method: str, path: str,
        *, headers: dict[str, str] | None = None,
    ) -> tuple[int, dict]:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        hdr_lines = ""
        if headers:
            for k, v in headers.items():
                hdr_lines += f"{k}: {v}\r\n"
        request = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n{hdr_lines}\r\n"
        writer.write(request.encode())
        await writer.drain()
        data = await reader.read(4096)
        writer.close()
        await writer.wait_closed()
        status_line = data.split(b"\r\n", 1)[0].decode()
        status_code = int(status_line.split(" ", 2)[1])
        body = data.split(b"\r\n\r\n", 1)[1]
        return status_code, json.loads(body)

    async def test_pause_without_token_401(self, auth_server) -> None:
        _, port = auth_server
        status, body = await self._request(port, "POST", "/pause")
        assert status == 401

    async def test_pause_with_wrong_token_401(self, auth_server) -> None:
        _, port = auth_server
        status, body = await self._request(
            port, "POST", "/pause",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert status == 401

    async def test_pause_with_correct_token_200(self, auth_server) -> None:
        _, port = auth_server
        status, body = await self._request(
            port, "POST", "/pause",
            headers={"Authorization": "Bearer test-secret"},
        )
        assert status == 200

    async def test_health_no_auth_required(self, auth_server) -> None:
        """GET /health should work without auth even when token is set."""
        _, port = auth_server
        status, body = await self._request(port, "GET", "/health")
        assert status == 200

    async def test_status_no_auth_required(self, auth_server) -> None:
        """GET /status should work without auth even when token is set."""
        _, port = auth_server
        status, body = await self._request(port, "GET", "/status")
        assert status == 200

    def test_requires_auth_or_explicit_local_opt_in(self) -> None:
        with pytest.raises(ValueError, match="requires auth_token by default"):
            HealthServer()

    def test_local_opt_in_rejects_non_loopback_host(self) -> None:
        with pytest.raises(ValueError, match="only allowed on loopback hosts"):
            HealthServer(host="0.0.0.0", allow_unauthenticated_local=True)
