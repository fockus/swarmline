"""Unit tests for PluginRunner — mocked subprocess."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarmline.plugins.runner import PluginRunner, SubprocessPluginRunner
from swarmline.plugins.runner_types import PluginHandle, PluginManifest, PluginState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> SubprocessPluginRunner:
    return SubprocessPluginRunner()


@pytest.fixture
def manifest() -> PluginManifest:
    return PluginManifest(name="test-plugin", entry_point="fake.module")


def _make_mock_process(
    pid: int = 42,
    returncode: int | None = None,
) -> MagicMock:
    """Create a mock asyncio.subprocess.Process."""
    proc = MagicMock()
    proc.pid = pid
    proc.returncode = returncode
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdout = MagicMock()
    proc.stderr = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


class TestProtocolShape:
    def test_protocol_shape_isinstance(self) -> None:
        """SubprocessPluginRunner must satisfy the PluginRunner protocol."""
        runner = SubprocessPluginRunner()
        assert isinstance(runner, PluginRunner)

    def test_protocol_has_four_methods(self) -> None:
        """PluginRunner protocol defines exactly 4 methods (ISP)."""
        methods = [
            name
            for name in dir(PluginRunner)
            if not name.startswith("_") and callable(getattr(PluginRunner, name, None))
        ]
        assert sorted(methods) == ["call", "health", "start", "stop"]


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


class TestStart:
    async def test_start_returns_handle_with_pid_and_running(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        mock_proc = _make_mock_process(pid=123)
        with patch.object(runner, "_launch", return_value=mock_proc):
            handle = await runner.start(manifest)

        assert isinstance(handle, PluginHandle)
        assert handle.pid == 123
        assert handle.state == PluginState.RUNNING
        assert handle.name == "test-plugin"
        assert handle.plugin_id  # non-empty string

    async def test_start_stores_process_internally(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        mock_proc = _make_mock_process(pid=99)
        with patch.object(runner, "_launch", return_value=mock_proc):
            handle = await runner.start(manifest)

        assert handle.plugin_id in runner._processes

    async def test_start_raises_on_immediate_crash(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        mock_proc = _make_mock_process(pid=10, returncode=1)
        with patch.object(runner, "_launch", return_value=mock_proc):
            with pytest.raises(RuntimeError, match="crashed immediately"):
                await runner.start(manifest)


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


class TestStop:
    async def test_stop_returns_true(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        mock_proc = _make_mock_process()
        with patch.object(runner, "_launch", return_value=mock_proc):
            handle = await runner.start(manifest)

        result = await runner.stop(handle)
        assert result is True
        assert handle.plugin_id not in runner._processes

    async def test_stop_unknown_handle_returns_false(
        self, runner: SubprocessPluginRunner
    ) -> None:
        fake_handle = PluginHandle(plugin_id="nonexistent", name="ghost")
        result = await runner.stop(fake_handle)
        assert result is False


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


class TestHealth:
    async def test_health_running_process(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        mock_proc = _make_mock_process()
        # Simulate ping response
        ping_response = (
            json.dumps(
                {"jsonrpc": "2.0", "result": {"ok": True}, "id": "ping"}
            ).encode()
            + b"\n"
        )
        mock_proc.stdout.readline = AsyncMock(return_value=ping_response)

        with patch.object(runner, "_launch", return_value=mock_proc):
            handle = await runner.start(manifest)

        state = await runner.health(handle)
        assert state == PluginState.RUNNING

    async def test_health_crashed_process(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        mock_proc = _make_mock_process()
        with patch.object(runner, "_launch", return_value=mock_proc):
            handle = await runner.start(manifest)

        # Simulate process death
        mock_proc.returncode = 1
        state = await runner.health(handle)
        assert state == PluginState.CRASHED

    async def test_health_unknown_handle_returns_stopped(
        self, runner: SubprocessPluginRunner
    ) -> None:
        fake_handle = PluginHandle(plugin_id="unknown", name="x")
        state = await runner.health(fake_handle)
        assert state == PluginState.STOPPED


# ---------------------------------------------------------------------------
# call
# ---------------------------------------------------------------------------


class TestCall:
    async def test_call_returns_result(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        mock_proc = _make_mock_process()
        rpc_response = (
            json.dumps(
                {"jsonrpc": "2.0", "result": {"echoed": "hi"}, "id": "abc"}
            ).encode()
            + b"\n"
        )
        mock_proc.stdout.readline = AsyncMock(return_value=rpc_response)

        with patch.object(runner, "_launch", return_value=mock_proc):
            handle = await runner.start(manifest)

        result = await runner.call(handle, "echo", {"message": "hi"})
        assert result == {"echoed": "hi"}

    async def test_call_raises_on_rpc_error(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        mock_proc = _make_mock_process()
        err_response = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": "Method not found: nope"},
                    "id": "abc",
                }
            ).encode()
            + b"\n"
        )
        mock_proc.stdout.readline = AsyncMock(return_value=err_response)

        with patch.object(runner, "_launch", return_value=mock_proc):
            handle = await runner.start(manifest)

        with pytest.raises(RuntimeError, match="Method not found"):
            await runner.call(handle, "nope")

    async def test_call_unknown_handle_raises_keyerror(
        self, runner: SubprocessPluginRunner
    ) -> None:
        fake_handle = PluginHandle(plugin_id="missing", name="x")
        with pytest.raises(KeyError, match="Unknown plugin"):
            await runner.call(fake_handle, "anything")
