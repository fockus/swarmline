"""Tests for cross-session memory - native + portable paths."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cognitia.runtime.ports.base import BaseRuntimePort
from cognitia.runtime.ports.deepagents import DeepAgentsRuntimePort
from cognitia.runtime.types import RuntimeConfig


class TestNativeMemoryPassedToUpstream:
    """Native path: memory_sources → native_config["memory"]."""

    def test_memory_sources_propagated_to_native_config(self) -> None:
        """DeepAgentsRuntimePort with memory_sources -> _config.native_config['memory']."""
        port = DeepAgentsRuntimePort(
            system_prompt="test",
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="native_first",
                allow_native_features=True,
            ),
            memory_sources=["./AGENTS.md", "~/.cognitia/AGENTS.md"],
        )
        assert port._config.native_config.get("memory") == [
            "./AGENTS.md",
            "~/.cognitia/AGENTS.md",
        ]

    def test_no_memory_sources_no_native_key(self) -> None:
        """Without memory_sources - native_config not contains memory klyuch."""
        port = DeepAgentsRuntimePort(
            system_prompt="test",
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="native_first",
            ),
        )
        assert "memory" not in port._config.native_config

    @pytest.mark.parametrize("feature_mode", ["hybrid", "native_first"])
    def test_native_modes_do_not_inject_memory_into_prompt(
        self,
        tmp_path,
        feature_mode: str,
    ) -> None:
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("Native memory source")

        port = DeepAgentsRuntimePort(
            system_prompt="You are helpful",
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode=feature_mode,
                allow_native_features=True,
            ),
            memory_sources=[str(agents_md)],
        )

        prompt = port._build_system_prompt()
        assert "<agent_memory>" not in prompt
        assert "Native memory source" not in prompt
        assert port._config.native_config.get("memory") == [str(agents_md)]


class TestAutoBackendForMemory:
    """Auto-backend: memory + no backend → auto-create FilesystemBackend."""

    def test_auto_backend_when_memory_but_no_backend(self) -> None:
        """memory_sources + native mode + no backend → auto-create backend."""
        mock_backend = MagicMock()
        mock_fs_module = MagicMock()
        mock_fs_module.FilesystemBackend.return_value = mock_backend

        import sys
        sys.modules["deepagents.backends.filesystem"] = mock_fs_module
        try:
            port = DeepAgentsRuntimePort(
                system_prompt="test",
                config=RuntimeConfig(
                    runtime_name="deepagents",
                    feature_mode="native_first",
                    allow_native_features=True,
                ),
                memory_sources=["./AGENTS.md"],
            )
            assert port._config.native_config.get("memory") == ["./AGENTS.md"]
            assert port._config.native_config.get("backend") is not None
        finally:
            del sys.modules["deepagents.backends.filesystem"]

    def test_no_auto_backend_when_backend_already_set(self) -> None:
        """If backend uzhe zadan - not perezapisyvaem."""
        existing_backend = MagicMock()
        port = DeepAgentsRuntimePort(
            system_prompt="test",
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="native_first",
                allow_native_features=True,
                native_config={"backend": existing_backend},
            ),
            memory_sources=["./AGENTS.md"],
        )
        assert port._config.native_config.get("backend") is existing_backend

    def test_no_auto_backend_without_memory_sources(self) -> None:
        """Without memory_sources - backend not sozdaetsya."""
        port = DeepAgentsRuntimePort(
            system_prompt="test",
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="native_first",
                allow_native_features=True,
            ),
        )
        assert "backend" not in port._config.native_config

    def test_no_auto_backend_in_portable_mode(self) -> None:
        """V portable mode - not create backend."""
        port = DeepAgentsRuntimePort(
            system_prompt="test",
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="portable",
            ),
            memory_sources=["./AGENTS.md"],
        )
        assert "backend" not in port._config.native_config


class TestPortableMemoryInjected:
    """Portable path: memory cherez inject_memory_into_prompt (read-only)."""

    def test_portable_mode_injects_memory(self, tmp_path) -> None:
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("Use snake_case in all code")

        port = DeepAgentsRuntimePort(
            system_prompt="You are helpful",
            config=RuntimeConfig(
                runtime_name="deepagents",
                feature_mode="portable",
            ),
            memory_sources=[str(agents_md)],
        )
        prompt = port._build_system_prompt()
        assert "<agent_memory>" in prompt
        assert "snake_case" in prompt

    def test_thin_runtime_port_injects_memory(self, tmp_path) -> None:
        """ThinRuntime cherez BaseRuntimePort takzhe inzhektit memory."""
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("Project conventions here")

        port = BaseRuntimePort(
            system_prompt="You are helpful",
            memory_sources=[str(agents_md)],
        )
        prompt = port._build_system_prompt()
        assert "<agent_memory>" in prompt
        assert "conventions" in prompt
