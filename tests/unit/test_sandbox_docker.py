"""Tests DockerSandboxProvider - mocked Docker SDK. TDD."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock

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


class TestDockerSandboxProvider:
    async def test_read_file(self, config) -> None:
        from swarmline.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        mock_container.exec_run.return_value = (0, b"file content")

        provider = DockerSandboxProvider(config, _container=mock_container)
        result = await provider.read_file("test.txt")
        assert result == "file content"

    async def test_write_file(self, config) -> None:
        from swarmline.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        mock_container.exec_run.return_value = (0, b"")

        provider = DockerSandboxProvider(config, _container=mock_container)
        await provider.write_file("test.txt", "hello")
        mock_container.exec_run.assert_called()

    async def test_execute(self, config) -> None:
        from swarmline.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        mock_container.exec_run.return_value = (0, b"output\n")

        provider = DockerSandboxProvider(config, _container=mock_container)
        result = await provider.execute("echo hello")
        assert result.stdout == "output\n"
        assert result.exit_code == 0

    async def test_execute_denied_command(self, config) -> None:
        from swarmline.tools.sandbox_docker import DockerSandboxProvider
        from swarmline.tools.types import SandboxViolation

        provider = DockerSandboxProvider(config, _container=AsyncMock())
        with pytest.raises(SandboxViolation):
            await provider.execute("rm -rf /")

    async def test_execute_denied_command_via_shell_wrapper_sh(self, config) -> None:
        from swarmline.tools.sandbox_docker import DockerSandboxProvider
        from swarmline.tools.types import SandboxViolation

        provider = DockerSandboxProvider(config, _container=AsyncMock())
        with pytest.raises(SandboxViolation):
            await provider.execute("sh -c 'rm -rf /'")

    async def test_execute_denied_command_via_shell_wrapper_bash(self, config) -> None:
        from swarmline.tools.sandbox_docker import DockerSandboxProvider
        from swarmline.tools.types import SandboxViolation

        provider = DockerSandboxProvider(config, _container=AsyncMock())
        with pytest.raises(SandboxViolation):
            await provider.execute('bash -lc "rm -rf /"')

    async def test_list_dir(self, config) -> None:
        from swarmline.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        mock_container.exec_run.return_value = (0, b"a.txt\nb.py\n")

        provider = DockerSandboxProvider(config, _container=mock_container)
        result = await provider.list_dir(".")
        assert sorted(result) == ["a.txt", "b.py"]

    async def test_glob_files(self, config) -> None:
        from swarmline.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        mock_container.exec_run.return_value = (0, b"main.py\nsrc/utils.py\n")

        provider = DockerSandboxProvider(config, _container=mock_container)
        result = await provider.glob_files("**/*.py")
        assert "main.py" in result

    async def test_glob_traversal_blocked(self, config) -> None:
        from swarmline.tools.sandbox_docker import DockerSandboxProvider
        from swarmline.tools.types import SandboxViolation

        provider = DockerSandboxProvider(config, _container=AsyncMock())
        with pytest.raises(SandboxViolation):
            await provider.glob_files("../../*.txt")

    async def test_isinstance_protocol(self, config) -> None:
        from swarmline.tools.protocols import SandboxProvider
        from swarmline.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        provider = DockerSandboxProvider(config, _container=mock_container)
        assert isinstance(provider, SandboxProvider)

    async def test_execute_timeout(self, config) -> None:
        import asyncio

        from swarmline.tools.sandbox_docker import DockerSandboxProvider

        async def slow_exec(*args, **kwargs):
            await asyncio.sleep(0.2)
            return (0, b"")

        tiny_timeout = SandboxConfig(
            root_path=config.root_path,
            user_id=config.user_id,
            topic_id=config.topic_id,
            timeout_seconds=0,
            denied_commands=config.denied_commands,
        )
        mock_container = AsyncMock()
        mock_container.exec_run.side_effect = slow_exec
        provider = DockerSandboxProvider(tiny_timeout, _container=mock_container)
        result = await provider.execute("echo slow")
        assert result.timed_out is True

    async def test_close_calls_stop_and_remove(self, config) -> None:
        from swarmline.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        provider = DockerSandboxProvider(config, _container=mock_container)
        await provider.close()
        assert mock_container.stop.called
        assert mock_container.remove.called

    async def test_dependency_or_daemon_error_raises_runtime_error(
        self, config, monkeypatch
    ) -> None:
        from swarmline.tools.sandbox_docker import DockerSandboxProvider

        class BrokenDocker:
            @staticmethod
            def from_env():
                raise RuntimeError("daemon down")

        monkeypatch.setitem(sys.modules, "docker", BrokenDocker)
        provider = DockerSandboxProvider(config)
        with pytest.raises(RuntimeError):
            await provider.read_file("test.txt")
