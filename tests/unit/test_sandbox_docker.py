"""Тесты DockerSandboxProvider — мокнутый Docker SDK. TDD."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cognitia.tools.types import SandboxConfig


@pytest.fixture()
def config() -> SandboxConfig:
    return SandboxConfig(root_path="/tmp", user_id="u1", topic_id="t1", timeout_seconds=5)


class TestDockerSandboxProvider:
    async def test_read_file(self, config) -> None:
        from cognitia.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        mock_container.exec_run.return_value = (0, b"file content")

        provider = DockerSandboxProvider(config, _container=mock_container)
        result = await provider.read_file("test.txt")
        assert result == "file content"

    async def test_write_file(self, config) -> None:
        from cognitia.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        mock_container.exec_run.return_value = (0, b"")

        provider = DockerSandboxProvider(config, _container=mock_container)
        await provider.write_file("test.txt", "hello")
        mock_container.exec_run.assert_called()

    async def test_execute(self, config) -> None:
        from cognitia.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        mock_container.exec_run.return_value = (0, b"output\n")

        provider = DockerSandboxProvider(config, _container=mock_container)
        result = await provider.execute("echo hello")
        assert result.stdout == "output\n"
        assert result.exit_code == 0

    async def test_list_dir(self, config) -> None:
        from cognitia.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        mock_container.exec_run.return_value = (0, b"a.txt\nb.py\n")

        provider = DockerSandboxProvider(config, _container=mock_container)
        result = await provider.list_dir(".")
        assert sorted(result) == ["a.txt", "b.py"]

    async def test_glob_files(self, config) -> None:
        from cognitia.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        mock_container.exec_run.return_value = (0, b"main.py\nsrc/utils.py\n")

        provider = DockerSandboxProvider(config, _container=mock_container)
        result = await provider.glob_files("**/*.py")
        assert "main.py" in result

    async def test_isinstance_protocol(self, config) -> None:
        from cognitia.tools.protocols import SandboxProvider
        from cognitia.tools.sandbox_docker import DockerSandboxProvider

        mock_container = AsyncMock()
        provider = DockerSandboxProvider(config, _container=mock_container)
        assert isinstance(provider, SandboxProvider)
