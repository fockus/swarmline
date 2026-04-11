"""Security tests for P2 fixes: SSRF, workspace injection, A2A auth,
Docker hardening, MCP trusted flag, daemon auth.

TDD Red phase: these tests define the expected behavior before implementation.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fix 1: SSRF protection — DNS resolution + redirect validation
# ---------------------------------------------------------------------------


class TestSSRFDnsResolution:
    """_validate_url must resolve DNS and block private IPs."""

    def test_ssrf_blocks_dns_resolved_private_loopback(self) -> None:
        """Hostname that resolves to 127.0.0.1 must be blocked."""
        from cognitia.tools.web_httpx import HttpxWebProvider

        fake_addrs = [
            (2, 1, 6, "", ("127.0.0.1", 0)),  # AF_INET, SOCK_STREAM
        ]
        with patch("cognitia.tools.web_httpx.socket.getaddrinfo", return_value=fake_addrs):
            result = HttpxWebProvider._validate_url("http://evil.example.com/data")
        assert result is not None
        assert "private" in result.lower() or "127.0.0.1" in result

    def test_ssrf_blocks_dns_resolved_private_rfc1918(self) -> None:
        """Hostname resolving to 10.x.x.x must be blocked."""
        from cognitia.tools.web_httpx import HttpxWebProvider

        fake_addrs = [
            (2, 1, 6, "", ("10.0.0.5", 0)),
        ]
        with patch("cognitia.tools.web_httpx.socket.getaddrinfo", return_value=fake_addrs):
            result = HttpxWebProvider._validate_url("http://internal.corp/api")
        assert result is not None
        assert "private" in result.lower() or "10.0.0.5" in result

    def test_ssrf_blocks_dns_resolved_link_local(self) -> None:
        """Hostname resolving to 169.254.x.x (link-local) must be blocked."""
        from cognitia.tools.web_httpx import HttpxWebProvider

        fake_addrs = [
            (2, 1, 6, "", ("169.254.1.1", 0)),
        ]
        with patch("cognitia.tools.web_httpx.socket.getaddrinfo", return_value=fake_addrs):
            result = HttpxWebProvider._validate_url("http://link-local-host.test/")
        assert result is not None

    def test_ssrf_allows_public_dns(self) -> None:
        """Hostname resolving to a public IP must be allowed."""
        from cognitia.tools.web_httpx import HttpxWebProvider

        fake_addrs = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ]
        with patch("cognitia.tools.web_httpx.socket.getaddrinfo", return_value=fake_addrs):
            result = HttpxWebProvider._validate_url("http://example.com/page")
        assert result is None

    def test_ssrf_blocks_localhost_hostname(self) -> None:
        """Literal 'localhost' must be blocked before DNS resolution."""
        from cognitia.tools.web_httpx import HttpxWebProvider

        result = HttpxWebProvider._validate_url("http://localhost:8080/admin")
        assert result is not None
        assert "localhost" in result.lower()

    def test_ssrf_blocks_localhost_localdomain(self) -> None:
        """'localhost.localdomain' must also be blocked."""
        from cognitia.tools.web_httpx import HttpxWebProvider

        result = HttpxWebProvider._validate_url("http://localhost.localdomain/admin")
        assert result is not None
        assert "localhost" in result.lower()

    def test_ssrf_dns_gaierror_passes(self) -> None:
        """If DNS resolution fails (gaierror), allow — will fail at fetch time."""
        import socket

        from cognitia.tools.web_httpx import HttpxWebProvider

        with patch(
            "cognitia.tools.web_httpx.socket.getaddrinfo",
            side_effect=socket.gaierror("Name resolution failed"),
        ):
            result = HttpxWebProvider._validate_url("http://nonexistent.invalid/")
        assert result is None

    async def test_ssrf_follow_redirects_disabled(self) -> None:
        """httpx client must NOT follow redirects automatically."""
        from cognitia.tools.web_httpx import HttpxWebProvider

        provider = HttpxWebProvider(timeout=5)

        # Mock socket.getaddrinfo to allow the URL
        fake_addrs = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with patch("cognitia.tools.web_httpx.socket.getaddrinfo", return_value=fake_addrs):
            mock_response = MagicMock()
            mock_response.is_redirect = False
            mock_response.status_code = 200
            mock_response.text = "<html><body>OK</body></html>"
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.build_request = MagicMock(side_effect=(
                    lambda method, url, **kwargs: {"method": method, "url": url, **kwargs}
                ))
                mock_client.send = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_client

                await provider.fetch("http://example.com/page")

                # Verify follow_redirects=False was passed
                mock_client_cls.assert_called_once()
                call_kwargs = mock_client_cls.call_args
                assert call_kwargs.kwargs.get("follow_redirects") is False or \
                    (len(call_kwargs.args) == 0 and call_kwargs[1].get("follow_redirects") is False)

    async def test_fetch_binds_request_to_resolved_public_ip(self) -> None:
        """Resolved public IP must be used for the connect path to avoid DNS rebinding."""
        from cognitia.tools.web_httpx import HttpxWebProvider

        provider = HttpxWebProvider(timeout=5)
        fake_addrs = [(2, 1, 6, "", ("93.184.216.34", 0))]

        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.text = "<html><body>OK</body></html>"
        mock_response.raise_for_status = MagicMock()

        sent_requests: list[Any] = []

        with patch("cognitia.tools.web_httpx.socket.getaddrinfo", return_value=fake_addrs):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.build_request = MagicMock(side_effect=(
                    lambda method, url, **kwargs: {"method": method, "url": url, **kwargs}
                ))

                async def _send(request):
                    sent_requests.append(request)
                    return mock_response

                mock_client.send.side_effect = _send
                mock_client_cls.return_value = mock_client

                result = await provider.fetch("https://example.com/page")

        assert "OK" in result
        assert len(sent_requests) == 1
        sent_request = sent_requests[0]
        assert sent_request["url"].startswith("https://93.184.216.34")
        assert sent_request["headers"]["host"] == "example.com"
        assert sent_request["extensions"]["sni_hostname"] == "example.com"

    async def test_fetch_blocks_private_redirect_hop(self) -> None:
        """Every redirect hop must be revalidated before issuing the next request."""
        from cognitia.tools.web_httpx import HttpxWebProvider

        provider = HttpxWebProvider(timeout=5)
        addrs = {
            "example.com": [(2, 1, 6, "", ("93.184.216.34", 0))],
            "metadata.internal": [(2, 1, 6, "", ("169.254.169.254", 0))],
        }

        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"location": "http://metadata.internal/secret"}
        redirect_response.raise_for_status = MagicMock()

        with patch(
            "cognitia.tools.web_httpx.socket.getaddrinfo",
            side_effect=lambda host, *_args, **_kwargs: addrs[host],
        ):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.build_request = MagicMock(side_effect=(
                    lambda method, url, **kwargs: {"method": method, "url": url, **kwargs}
                ))
                mock_client.send = AsyncMock(return_value=redirect_response)
                mock_client_cls.return_value = mock_client

                result = await provider.fetch("http://example.com/start")

        assert "URL blocked" in result
        assert mock_client.send.await_count == 1

    async def test_fetch_logs_security_decision_for_blocked_target(self) -> None:
        """Blocked targets must emit a structured security decision log."""
        from cognitia.tools.web_httpx import HttpxWebProvider

        provider = HttpxWebProvider(timeout=5)

        with patch("cognitia.tools.web_httpx._log") as mock_log:
            result = await provider.fetch("http://localhost:8080/admin")

        assert "URL blocked" in result
        mock_log.warning.assert_called_once_with(
            "security_decision",
            event_name="security.network_target_denied",
            component="web_httpx",
            decision="deny",
            reason="Blocked host: localhost",
            target="localhost",
            url="http://localhost:8080/admin",
        )


# ---------------------------------------------------------------------------
# Fix 2: Workspace path injection
# ---------------------------------------------------------------------------


class TestWorkspacePathInjection:
    """agent_id and task_id must be validated as safe slugs."""

    async def test_workspace_rejects_path_traversal_agent_id(self) -> None:
        """agent_id with '../' must raise ValueError."""
        from cognitia.multi_agent.workspace import LocalWorkspace
        from cognitia.multi_agent.workspace_types import WorkspaceSpec, WorkspaceStrategy

        ws = LocalWorkspace()
        spec = WorkspaceSpec(strategy=WorkspaceStrategy.TEMP_DIR, base_path="/tmp")
        with pytest.raises(ValueError, match="Invalid agent_id"):
            await ws.create(spec, "../../evil", "task1")

    async def test_workspace_rejects_path_traversal_task_id(self) -> None:
        """task_id with '../' must raise ValueError."""
        from cognitia.multi_agent.workspace import LocalWorkspace
        from cognitia.multi_agent.workspace_types import WorkspaceSpec, WorkspaceStrategy

        ws = LocalWorkspace()
        spec = WorkspaceSpec(strategy=WorkspaceStrategy.TEMP_DIR, base_path="/tmp")
        with pytest.raises(ValueError, match="Invalid task_id"):
            await ws.create(spec, "agent1", "../../../etc/passwd")

    async def test_workspace_rejects_slash_in_agent_id(self) -> None:
        """agent_id with '/' must raise ValueError."""
        from cognitia.multi_agent.workspace import LocalWorkspace
        from cognitia.multi_agent.workspace_types import WorkspaceSpec, WorkspaceStrategy

        ws = LocalWorkspace()
        spec = WorkspaceSpec(strategy=WorkspaceStrategy.TEMP_DIR, base_path="/tmp")
        with pytest.raises(ValueError, match="Invalid agent_id"):
            await ws.create(spec, "path/injection", "task1")

    async def test_workspace_rejects_empty_agent_id(self) -> None:
        """Empty agent_id must raise ValueError."""
        from cognitia.multi_agent.workspace import LocalWorkspace
        from cognitia.multi_agent.workspace_types import WorkspaceSpec, WorkspaceStrategy

        ws = LocalWorkspace()
        spec = WorkspaceSpec(strategy=WorkspaceStrategy.TEMP_DIR, base_path="/tmp")
        with pytest.raises(ValueError, match="Invalid agent_id"):
            await ws.create(spec, "", "task1")

    async def test_workspace_accepts_valid_slugs(self) -> None:
        """Valid alphanumeric slugs with dashes and underscores must work."""
        from cognitia.multi_agent.workspace import LocalWorkspace
        from cognitia.multi_agent.workspace_types import WorkspaceSpec, WorkspaceStrategy

        ws = LocalWorkspace()
        spec = WorkspaceSpec(strategy=WorkspaceStrategy.TEMP_DIR, base_path="/tmp")
        handle = await ws.create(spec, "agent-01_test", "task-42_final")
        try:
            assert handle.agent_id == "agent-01_test"
            assert handle.task_id == "task-42_final"
        finally:
            await ws.cleanup(handle)


# ---------------------------------------------------------------------------
# Fix 3: A2A server auth + request size limit
# ---------------------------------------------------------------------------


class TestA2AServerAuth:
    """A2A server must enforce Bearer token auth and request size limits."""

    def _make_auth_server(
        self, auth_token: str | None = None, max_request_size: int = 1_048_576
    ) -> tuple[Any, Any]:
        pytest.importorskip("starlette")
        from starlette.testclient import TestClient

        from cognitia.a2a.adapter import CognitiaA2AAdapter
        from cognitia.a2a.server import A2AServer
        from cognitia.a2a.types import AgentSkill
        from cognitia.agent.result import Result

        agent = MagicMock()
        agent.query = AsyncMock(return_value=Result(text="OK"))
        adapter = CognitiaA2AAdapter(
            agent,
            name="AuthBot",
            url="http://localhost:8000",
            skills=[AgentSkill(id="test", name="Test")],
        )
        server = A2AServer(
            adapter,
            auth_token=auth_token,
            max_request_size=max_request_size,
        )
        client = TestClient(server.app)
        return server, client

    def test_a2a_auth_rejects_unauthenticated(self) -> None:
        """Request without token to auth-enabled server returns 401."""
        _, client = self._make_auth_server(auth_token="secret-token-123")
        resp = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tasks/send",
                "params": {"task": {"id": "t1", "message": "Hi"}},
            },
        )
        assert resp.status_code == 401

    def test_a2a_auth_rejects_wrong_token(self) -> None:
        """Request with wrong token returns 401."""
        _, client = self._make_auth_server(auth_token="secret-token-123")
        resp = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tasks/send",
                "params": {"task": {"id": "t1", "message": "Hi"}},
            },
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_a2a_auth_accepts_correct_token(self) -> None:
        """Request with correct token succeeds."""
        _, client = self._make_auth_server(auth_token="secret-token-123")
        resp = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tasks/send",
                "params": {"task": {"id": "t1", "message": "Hi"}},
            },
            headers={"Authorization": "Bearer secret-token-123"},
        )
        assert resp.status_code == 200
        assert "result" in resp.json()

    def test_a2a_no_auth_allows_all(self) -> None:
        """Server without auth_token allows unauthenticated requests."""
        _, client = self._make_auth_server(auth_token=None)
        resp = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tasks/send",
                "params": {"task": {"id": "t1", "message": "Hi"}},
            },
        )
        assert resp.status_code == 200

    def test_a2a_discovery_skips_auth(self) -> None:
        """GET /.well-known/agent.json must work without auth even when token is set."""
        _, client = self._make_auth_server(auth_token="secret-token-123")
        resp = client.get("/.well-known/agent.json")
        assert resp.status_code == 200
        assert resp.json()["name"] == "AuthBot"

    def test_a2a_request_too_large_rejected(self) -> None:
        """Request exceeding max_request_size returns JSON-RPC error."""
        _, client = self._make_auth_server(max_request_size=100)
        # Build a payload larger than 100 bytes
        large_payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tasks/send",
            "params": {"task": {"id": "t1", "message": "A" * 200}},
        }
        resp = client.post("/", json=large_payload)
        assert resp.status_code == 200  # JSON-RPC errors use 200 status
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == -32600
        assert "too large" in body["error"]["message"].lower()


# ---------------------------------------------------------------------------
# Fix 4: Docker sandbox hardening
# ---------------------------------------------------------------------------


class TestDockerSandboxHardening:
    """Container must be started with security hardening options."""

    async def test_docker_default_cap_drop(self) -> None:
        """containers.run must be called with cap_drop=['ALL']."""
        from cognitia.tools.types import SandboxConfig

        config = SandboxConfig(
            root_path="/tmp",
            user_id="u1",
            topic_id="t1",
            timeout_seconds=5,
        )

        mock_docker_module = MagicMock()
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.containers.run.return_value = mock_container
        mock_docker_module.from_env.return_value = mock_client

        with patch.dict(sys.modules, {"docker": mock_docker_module}):
            import cognitia.tools.sandbox_docker as sd_mod

            provider = sd_mod.DockerSandboxProvider(config)
            await provider._ensure_container()

            mock_client.containers.run.assert_called_once()
            call_kwargs = mock_client.containers.run.call_args
            assert call_kwargs.kwargs.get("cap_drop") == ["ALL"] or \
                (len(call_kwargs) > 1 and call_kwargs[1].get("cap_drop") == ["ALL"])

    async def test_docker_no_new_privileges(self) -> None:
        """containers.run must be called with security_opt=['no-new-privileges=true']."""
        from cognitia.tools.sandbox_docker import DockerSandboxProvider
        from cognitia.tools.types import SandboxConfig

        config = SandboxConfig(
            root_path="/tmp",
            user_id="u1",
            topic_id="t1",
            timeout_seconds=5,
        )

        mock_docker_module = MagicMock()
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.containers.run.return_value = mock_container
        mock_docker_module.from_env.return_value = mock_client

        with patch.dict(sys.modules, {"docker": mock_docker_module}):
            provider = DockerSandboxProvider(config)
            await provider._ensure_container()

            call_kwargs = mock_client.containers.run.call_args
            security_opt = call_kwargs.kwargs.get("security_opt") or \
                (call_kwargs[1].get("security_opt") if len(call_kwargs) > 1 else None)
            assert security_opt is not None
            assert "no-new-privileges=true" in security_opt


# ---------------------------------------------------------------------------
# Fix 5: MCP code exec trusted-only flag
# ---------------------------------------------------------------------------


class TestMCPExecTrustedFlag:
    """exec_code must require trusted=True to execute."""

    async def test_mcp_exec_requires_trusted_default_blocks(self) -> None:
        """Calling exec_code without trusted=True must return error."""
        from cognitia.mcp._tools_code import exec_code

        result = await exec_code("print('hello')")
        assert result["ok"] is False
        assert "trusted" in result["error"].lower()

    async def test_mcp_exec_trusted_true_allows_execution(self) -> None:
        """Calling exec_code with trusted=True must execute the code."""
        from cognitia.mcp._tools_code import exec_code

        result = await exec_code("print(42)", trusted=True)
        assert result["ok"] is True
        assert result["data"]["stdout"] == "42"

    async def test_mcp_exec_trusted_false_explicit_blocks(self) -> None:
        """Explicitly passing trusted=False must block execution."""
        from cognitia.mcp._tools_code import exec_code

        result = await exec_code("print('hello')", trusted=False)
        assert result["ok"] is False
        assert "trusted" in result["error"].lower()


# ---------------------------------------------------------------------------
# Fix 6: Daemon health auth through config
# ---------------------------------------------------------------------------


class TestDaemonHealthAuth:
    """DaemonConfig.auth_token must propagate to HealthServer."""

    def test_daemon_config_has_auth_token_field(self) -> None:
        """DaemonConfig must accept auth_token parameter."""
        from cognitia.daemon.types import DaemonConfig

        config = DaemonConfig(auth_token="my-secret")
        assert config.auth_token == "my-secret"

    def test_daemon_config_auth_token_default_none(self) -> None:
        """DaemonConfig.auth_token defaults to None."""
        from cognitia.daemon.types import DaemonConfig

        config = DaemonConfig()
        assert config.auth_token is None

    def test_daemon_runner_passes_auth_to_health(self, tmp_path: Any) -> None:
        """DaemonRunner must pass auth_token from config to HealthServer."""
        from cognitia.daemon.runner import DaemonRunner
        from cognitia.daemon.types import DaemonConfig

        config = DaemonConfig(
            pid_path=str(tmp_path / "test.pid"),
            health_port=0,
            auth_token="runner-secret",
        )
        runner = DaemonRunner(config=config)
        # The health server should have the auth_token set
        assert runner._health._auth_token == "runner-secret"

    def test_daemon_runner_no_auth_when_not_set(self, tmp_path: Any) -> None:
        """DaemonRunner without auth_token creates HealthServer without auth."""
        from cognitia.daemon.runner import DaemonRunner
        from cognitia.daemon.types import DaemonConfig

        config = DaemonConfig(
            pid_path=str(tmp_path / "test.pid"),
            health_port=0,
        )
        runner = DaemonRunner(config=config)
        assert runner._health._auth_token is None
