"""Unit tests for PluginRunner — mocked subprocess."""

from __future__ import annotations

import json
import os
import types
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
    async def test_launch_default_env_does_not_inherit_host_secret(
        self, monkeypatch: pytest.MonkeyPatch, manifest: PluginManifest
    ) -> None:
        """Default plugin subprocess env forwards allowlist only."""
        captured: dict[str, object] = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["args"] = args
            captured["env"] = kwargs["env"]
            return _make_mock_process()

        monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-plugin-secret-1234567890abcdef")
        monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
        monkeypatch.setattr(
            "swarmline.plugins.runner.asyncio.create_subprocess_exec",
            fake_create_subprocess_exec,
        )

        runner = SubprocessPluginRunner()
        await runner._launch(manifest)

        env = captured["env"]
        assert isinstance(env, dict)
        assert "PATH" in env
        assert "OPENAI_API_KEY" not in env

    async def test_launch_explicit_env_override_is_forwarded(
        self, manifest: PluginManifest
    ) -> None:
        captured: dict[str, object] = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["env"] = kwargs["env"]
            return _make_mock_process()

        with patch(
            "swarmline.plugins.runner.asyncio.create_subprocess_exec",
            side_effect=fake_create_subprocess_exec,
        ):
            runner = SubprocessPluginRunner(env={"PLUGIN_MODE": "test"})
            await runner._launch(manifest)

        env = captured["env"]
        assert isinstance(env, dict)
        assert env["PLUGIN_MODE"] == "test"

    async def test_launch_inherit_host_env_preserves_legacy_env(
        self, monkeypatch: pytest.MonkeyPatch, manifest: PluginManifest
    ) -> None:
        captured: dict[str, object] = {}

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured["env"] = kwargs["env"]
            return _make_mock_process()

        monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-plugin-secret-1234567890abcdef")
        monkeypatch.setattr(
            "swarmline.plugins.runner.asyncio.create_subprocess_exec",
            fake_create_subprocess_exec,
        )

        runner = SubprocessPluginRunner(inherit_host_env=True)
        await runner._launch(manifest)

        env = captured["env"]
        assert isinstance(env, dict)
        assert env["OPENAI_API_KEY"] == "sk-proj-plugin-secret-1234567890abcdef"

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

    async def test_start_drains_stderr_until_stop(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        mock_proc = _make_mock_process(pid=124)
        mock_proc.stderr.readline = AsyncMock(
            side_effect=[b"diagnostic sk-secret-value-1234567890\n", b""]
        )
        with patch.object(runner, "_launch", return_value=mock_proc):
            handle = await runner.start(manifest)

        pp = runner._processes[handle.plugin_id]
        assert pp.stderr_task is not None
        await pp.stderr_task

        result = await runner.stop(handle)
        assert result is True
        assert pp.stderr_task.done()


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


class TestWorkerShimRpcAllowlist:
    def test_worker_shim_allows_public_callable_without_all(self) -> None:
        from swarmline.plugins._worker_shim import _is_rpc_method_allowed

        module = types.SimpleNamespace(public=lambda: "ok", _private=lambda: "no")

        assert _is_rpc_method_allowed(module, "public") is True

    @pytest.mark.parametrize("method", ["_private", "__dunder__"])
    def test_worker_shim_rejects_private_methods_without_all(self, method: str) -> None:
        from swarmline.plugins._worker_shim import _is_rpc_method_allowed

        module = types.SimpleNamespace(
            _private=lambda: "no",
            __dunder__=lambda: "no",
        )

        assert _is_rpc_method_allowed(module, method) is False

    def test_worker_shim_respects_module_all(self) -> None:
        from swarmline.plugins._worker_shim import _is_rpc_method_allowed

        module = types.SimpleNamespace(
            __all__=["exported"],
            exported=lambda: "ok",
            public_but_not_exported=lambda: "no",
        )

        assert _is_rpc_method_allowed(module, "exported") is True
        assert _is_rpc_method_allowed(module, "public_but_not_exported") is False
