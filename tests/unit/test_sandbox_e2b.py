"""Tests E2BSandboxProvider - mocked E2B SDK. TDD."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from swarmline.tools.types import SandboxConfig


@pytest.fixture()
def config() -> SandboxConfig:
    return SandboxConfig(
        root_path="/tmp",
        user_id="u1",
        topic_id="t1",
        timeout_seconds=5,
        denied_commands=frozenset({"rm"}),
    )


class TestE2BSandboxProvider:
    async def test_read_file(self, config) -> None:
        from swarmline.tools.sandbox_e2b import E2BSandboxProvider

        mock_sandbox = AsyncMock()
        mock_sandbox.filesystem.read.return_value = "content"

        provider = E2BSandboxProvider(config, _sandbox=mock_sandbox)
        result = await provider.read_file("test.txt")
        assert result == "content"

    async def test_write_file(self, config) -> None:
        from swarmline.tools.sandbox_e2b import E2BSandboxProvider

        mock_sandbox = AsyncMock()
        provider = E2BSandboxProvider(config, _sandbox=mock_sandbox)
        await provider.write_file("test.txt", "hello")
        mock_sandbox.filesystem.write.assert_called_once()

    async def test_execute(self, config) -> None:
        from swarmline.tools.sandbox_e2b import E2BSandboxProvider

        mock_sandbox = AsyncMock()
        mock_proc = MagicMock()
        mock_proc.stdout = "output"
        mock_proc.stderr = ""
        mock_proc.exit_code = 0
        mock_sandbox.process.start.return_value = mock_proc

        provider = E2BSandboxProvider(config, _sandbox=mock_sandbox)
        result = await provider.execute("echo test")
        assert result.stdout == "output"
        assert result.exit_code == 0
        assert result.timed_out is False

    async def test_execute_denied_command(self, config) -> None:
        from swarmline.tools.sandbox_e2b import E2BSandboxProvider
        from swarmline.tools.types import SandboxViolation

        provider = E2BSandboxProvider(config, _sandbox=AsyncMock())
        with pytest.raises(SandboxViolation):
            await provider.execute("rm -rf /")

    async def test_list_dir(self, config) -> None:
        from swarmline.tools.sandbox_e2b import E2BSandboxProvider

        mock_sandbox = AsyncMock()
        mock_sandbox.filesystem.list.return_value = [
            MagicMock(name="a.txt"),
            MagicMock(name="b.py"),
        ]
        # Mock .name explicitly because MagicMock(name=) is intercepted
        mock_sandbox.filesystem.list.return_value[0].name = "a.txt"
        mock_sandbox.filesystem.list.return_value[1].name = "b.py"

        provider = E2BSandboxProvider(config, _sandbox=mock_sandbox)
        result = await provider.list_dir(".")
        assert sorted(result) == ["a.txt", "b.py"]

    async def test_glob_files(self, config) -> None:
        from swarmline.tools.sandbox_e2b import E2BSandboxProvider

        mock_sandbox = AsyncMock()
        # Glob via execute + find
        mock_proc = MagicMock()
        mock_proc.stdout = (
            "/home/user/workspace/main.py\n/home/user/workspace/src/utils.py\n"
        )
        mock_proc.stderr = ""
        mock_proc.exit_code = 0
        mock_sandbox.process.start.return_value = mock_proc

        provider = E2BSandboxProvider(config, _sandbox=mock_sandbox)
        result = await provider.glob_files("**/*.py")
        assert "main.py" in result

    async def test_isinstance_protocol(self, config) -> None:
        from swarmline.tools.protocols import SandboxProvider
        from swarmline.tools.sandbox_e2b import E2BSandboxProvider

        mock_sandbox = AsyncMock()
        provider = E2BSandboxProvider(config, _sandbox=mock_sandbox)
        assert isinstance(provider, SandboxProvider)

    async def test_dependency_missing_raises_runtime_error(self, config) -> None:
        from swarmline.tools.sandbox_e2b import E2BSandboxProvider

        provider = E2BSandboxProvider(config)
        with pytest.raises(RuntimeError):
            await provider.read_file("a.txt")

    async def test_execute_timeout(self, config) -> None:
        from swarmline.tools.sandbox_e2b import E2BSandboxProvider

        mock_sandbox = AsyncMock()

        async def slow_start(*args, **kwargs):
            await asyncio.sleep(0.2)
            return MagicMock(stdout="", stderr="", exit_code=0)

        tiny_timeout = SandboxConfig(
            root_path=config.root_path,
            user_id=config.user_id,
            topic_id=config.topic_id,
            timeout_seconds=0,
            denied_commands=config.denied_commands,
        )
        mock_sandbox.process.start.side_effect = slow_start
        provider = E2BSandboxProvider(tiny_timeout, _sandbox=mock_sandbox)
        result = await provider.execute("echo hi")
        assert result.timed_out is True

    async def test_close_calls_kill_or_close(self, config) -> None:
        from swarmline.tools.sandbox_e2b import E2BSandboxProvider

        sandbox = AsyncMock()
        provider = E2BSandboxProvider(config, _sandbox=sandbox)
        await provider.close()
        assert sandbox.kill.called or sandbox.close.called
