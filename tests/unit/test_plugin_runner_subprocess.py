"""Subprocess integration tests for PluginRunner -- real processes."""

from __future__ import annotations

import asyncio
import os
import textwrap
from pathlib import Path

import pytest

from swarmline.plugins.runner import SubprocessPluginRunner
from swarmline.plugins.runner_types import PluginManifest, PluginState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ECHO_PLUGIN_SOURCE = textwrap.dedent("""\
    \"\"\"Tiny test plugin for subprocess integration tests.\"\"\"

    import time

    def echo(message: str = "") -> dict:
        return {"echoed": message}

    def add(a: int = 0, b: int = 0) -> dict:
        return {"sum": a + b}

    def slow(label: str = "slow", delay: float = 0.1) -> dict:
        time.sleep(delay)
        return {"name": label}

    def fail() -> None:
        raise ValueError("intentional test error")
""")


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
    """Write the echo plugin to a temp directory and return the dir."""
    plugin_file = tmp_path / "echo_plugin.py"
    plugin_file.write_text(ECHO_PLUGIN_SOURCE)
    return tmp_path


@pytest.fixture
def subprocess_env(plugin_dir: Path) -> dict[str, str]:
    """Build an env dict that lets the child process find the echo plugin."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(plugin_dir) + (os.pathsep + existing if existing else "")
    return env


@pytest.fixture
def runner(subprocess_env: dict[str, str]) -> SubprocessPluginRunner:
    return SubprocessPluginRunner(env=subprocess_env)


@pytest.fixture
def manifest() -> PluginManifest:
    return PluginManifest(
        name="echo-test",
        entry_point="echo_plugin",
        timeout_seconds=5.0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSubprocessLifecycle:
    async def test_start_real_subprocess(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        handle = await runner.start(manifest)
        try:
            assert handle.pid is not None
            assert handle.state == PluginState.RUNNING
            assert handle.name == "echo-test"
        finally:
            await runner.stop(handle)

    async def test_stop_graceful(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        handle = await runner.start(manifest)
        result = await runner.stop(handle)
        assert result is True

    async def test_ping_health(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        handle = await runner.start(manifest)
        try:
            state = await runner.health(handle)
            assert state == PluginState.RUNNING
        finally:
            await runner.stop(handle)


class TestSubprocessCall:
    async def test_call_echo(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        handle = await runner.start(manifest)
        try:
            result = await runner.call(handle, "echo", {"message": "hello"})
            assert result == {"echoed": "hello"}
        finally:
            await runner.stop(handle)

    async def test_call_add(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        handle = await runner.start(manifest)
        try:
            result = await runner.call(handle, "add", {"a": 2, "b": 3})
            assert result == {"sum": 5}
        finally:
            await runner.stop(handle)

    async def test_call_method_not_found(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        handle = await runner.start(manifest)
        try:
            with pytest.raises(RuntimeError, match="Method not found"):
                await runner.call(handle, "nonexistent_method")
        finally:
            await runner.stop(handle)

    async def test_call_method_error(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        handle = await runner.start(manifest)
        try:
            with pytest.raises(RuntimeError, match="intentional"):
                await runner.call(handle, "fail")
        finally:
            await runner.stop(handle)

    async def test_call_timeout(
        self, runner: SubprocessPluginRunner
    ) -> None:
        """A very short timeout should cause TimeoutError / asyncio timeout."""
        short_manifest = PluginManifest(
            name="echo-timeout",
            entry_point="echo_plugin",
            timeout_seconds=0.0001,
        )
        handle = await runner.start(short_manifest)
        try:
            with pytest.raises((asyncio.TimeoutError, RuntimeError)):
                await runner.call(handle, "echo", {"message": "slow"})
        finally:
            await runner.stop(handle)

    async def test_call_concurrent_requests_on_same_handle(
        self, runner: SubprocessPluginRunner, manifest: PluginManifest
    ) -> None:
        handle = await runner.start(manifest)
        try:
            slow_result, fast_result = await asyncio.gather(
                runner.call(handle, "slow", {"label": "slow", "delay": 0.1}),
                runner.call(handle, "echo", {"message": "fast"}),
            )
        finally:
            await runner.stop(handle)

        assert slow_result == {"name": "slow"}
        assert fast_result == {"echoed": "fast"}
