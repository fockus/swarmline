"""Smoke: import cognitia modules without optional extras.

Verifies that `import cognitia` and core submodules work
when optional dependencies (claude_agent_sdk, anthropic, langchain) are absent.
"""

from __future__ import annotations

import sys
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest


@contextmanager
def _block_packages(*names: str) -> Generator[None, None, None]:
    """Temporarily make packages unimportable."""
    saved: dict[str, Any] = {}
    saved_cognitia = {
        key: value
        for key, value in sys.modules.items()
        if key == "cognitia" or key.startswith("cognitia.")
    }
    for name in names:
        # Block the package itself and all subpackages already loaded
        keys_to_block = [k for k in sys.modules if k == name or k.startswith(f"{name}.")]
        for k in keys_to_block:
            saved[k] = sys.modules.pop(k)
        # Sentinel that prevents import
        sys.modules[name] = None  # type: ignore[assignment]
    try:
        yield
    finally:
        # Restore
        for name in names:
            sys.modules.pop(name, None)
        for key in list(sys.modules):
            if key == "cognitia" or key.startswith("cognitia."):
                sys.modules.pop(key)
        sys.modules.update(saved)
        sys.modules.update(saved_cognitia)


# -- Core library (no optional deps) --


class TestCoreImportsWithoutOptionalDeps:
    """Import core cognitia without any optional dependencies."""

    def test_import_cognitia_top_level(self) -> None:
        """Top-level `import cognitia` must work without optional deps."""
        with _block_packages(
            "claude_agent_sdk", "anthropic", "langchain_core", "langchain_anthropic"
        ):
            # Force reimport
            for key in list(sys.modules):
                if key.startswith("cognitia"):
                    del sys.modules[key]
            import cognitia

            assert hasattr(cognitia, "__version__")

    def test_import_runtime_types(self) -> None:
        with _block_packages(
            "claude_agent_sdk", "anthropic", "langchain_core", "langchain_anthropic"
        ):
            for key in list(sys.modules):
                if key.startswith("cognitia.runtime"):
                    del sys.modules[key]
            from cognitia.runtime.types import Message

            assert Message is not None

    def test_import_runtime_factory(self) -> None:
        with _block_packages(
            "claude_agent_sdk", "anthropic", "langchain_core", "langchain_anthropic"
        ):
            for key in list(sys.modules):
                if key.startswith("cognitia.runtime"):
                    del sys.modules[key]
            from cognitia.runtime.factory import RuntimeFactory

            assert RuntimeFactory is not None

    def test_import_memory(self) -> None:
        with _block_packages(
            "claude_agent_sdk", "anthropic", "langchain_core", "langchain_anthropic"
        ):
            for key in list(sys.modules):
                if key.startswith("cognitia.memory"):
                    del sys.modules[key]
            from cognitia.memory import InMemoryMemoryProvider

            assert InMemoryMemoryProvider is not None

    def test_import_context(self) -> None:
        with _block_packages("claude_agent_sdk"):
            for key in list(sys.modules):
                if key.startswith("cognitia.context"):
                    del sys.modules[key]
            from cognitia.context import DefaultContextBuilder

            assert DefaultContextBuilder is not None

    def test_import_policy(self) -> None:
        with _block_packages("claude_agent_sdk"):
            for key in list(sys.modules):
                if key.startswith("cognitia.policy"):
                    del sys.modules[key]
            from cognitia.policy import DefaultToolPolicy

            assert DefaultToolPolicy is not None

    def test_import_routing(self) -> None:
        with _block_packages("claude_agent_sdk"):
            for key in list(sys.modules):
                if key.startswith("cognitia.routing"):
                    del sys.modules[key]
            from cognitia.routing import KeywordRoleRouter

            assert KeywordRoleRouter is not None

    def test_import_hooks_without_sdk(self) -> None:
        """hooks module works without claude_agent_sdk."""
        with _block_packages("claude_agent_sdk"):
            for key in list(sys.modules):
                if key.startswith("cognitia.hooks"):
                    del sys.modules[key]
            from cognitia.hooks import HookRegistry

            assert HookRegistry is not None

    def test_runtime_adapter_reexport_fails_fast_without_sdk(self) -> None:
        """Optional runtime re-export should raise, not expose None."""
        with _block_packages("claude_agent_sdk"):
            for key in list(sys.modules):
                if key.startswith("cognitia.runtime"):
                    del sys.modules[key]

            with pytest.raises(ImportError, match="RuntimeAdapter"):
                from cognitia.runtime import RuntimeAdapter  # noqa: F401

    def test_runtime_star_import_skips_optional_exports_without_sdk(self) -> None:
        """Star import should keep core runtime symbols available without SDK extras."""
        with _block_packages("claude_agent_sdk"):
            for key in list(sys.modules):
                if key.startswith("cognitia.runtime"):
                    del sys.modules[key]

            namespace: dict[str, Any] = {}
            exec("from cognitia.runtime import *", namespace)

            assert "RuntimeFactory" in namespace
            assert "RuntimeAdapter" not in namespace
            assert "ClaudeOptionsBuilder" not in namespace

    def test_hooks_sdk_bridge_reexport_fails_fast_without_sdk(self) -> None:
        """Optional hooks bridge should raise, not expose None."""
        with _block_packages("claude_agent_sdk"):
            for key in list(sys.modules):
                if key.startswith("cognitia.hooks"):
                    del sys.modules[key]

            with pytest.raises(ImportError, match="registry_to_sdk_hooks"):
                from cognitia.hooks import registry_to_sdk_hooks  # noqa: F401

    def test_hooks_star_import_skips_sdk_bridge_without_sdk(self) -> None:
        """Star import should not force SDK hook bridge import."""
        with _block_packages("claude_agent_sdk"):
            for key in list(sys.modules):
                if key.startswith("cognitia.hooks"):
                    del sys.modules[key]

            namespace: dict[str, Any] = {}
            exec("from cognitia.hooks import *", namespace)

            assert "HookRegistry" in namespace
            assert "registry_to_sdk_hooks" not in namespace

    def test_runtime_ports_reexports_fail_fast_when_optional_modules_unavailable(self) -> None:
        """Optional runtime ports should fail fast when port modules cannot be imported."""
        with _block_packages("cognitia.runtime.ports.thin", "cognitia.runtime.ports.deepagents"):
            for key in list(sys.modules):
                if key.startswith("cognitia.runtime") and key not in {
                    "cognitia.runtime.ports.thin",
                    "cognitia.runtime.ports.deepagents",
                }:
                    del sys.modules[key]

            with pytest.raises(ImportError, match="ThinRuntimePort"):
                from cognitia.runtime import ThinRuntimePort  # noqa: F401

            with pytest.raises(ImportError, match="DeepAgentsRuntimePort"):
                from cognitia.runtime.ports import DeepAgentsRuntimePort  # noqa: F401

    def test_runtime_ports_star_import_skips_optional_ports_when_unavailable(self) -> None:
        """Star import should expose only base runtime port symbols."""
        with _block_packages("cognitia.runtime.ports.thin", "cognitia.runtime.ports.deepagents"):
            for key in list(sys.modules):
                if key.startswith("cognitia.runtime") and key not in {
                    "cognitia.runtime.ports.thin",
                    "cognitia.runtime.ports.deepagents",
                }:
                    del sys.modules[key]

            namespace: dict[str, Any] = {}
            exec("from cognitia.runtime.ports import *", namespace)

            assert "BaseRuntimePort" in namespace
            assert "ThinRuntimePort" not in namespace
            assert "DeepAgentsRuntimePort" not in namespace

    def test_memory_optional_providers_fail_fast_without_sqlalchemy(self) -> None:
        """Optional memory providers should raise instead of disappearing."""
        with _block_packages("sqlalchemy"):
            for key in list(sys.modules):
                if key.startswith("cognitia.memory") and key != "sqlalchemy":
                    del sys.modules[key]

            with pytest.raises(ImportError, match="SQLiteMemoryProvider"):
                from cognitia.memory import SQLiteMemoryProvider  # noqa: F401

            with pytest.raises(ImportError, match="PostgresMemoryProvider"):
                from cognitia.memory import PostgresMemoryProvider  # noqa: F401

    def test_skills_optional_loader_fail_fast_without_loader_module(self) -> None:
        """Optional skill loader exports should raise instead of disappearing."""
        with _block_packages("cognitia.skills.loader"):
            for key in list(sys.modules):
                if key.startswith("cognitia.skills") and key != "cognitia.skills.loader":
                    del sys.modules[key]

            with pytest.raises(ImportError, match="YamlSkillLoader"):
                from cognitia.skills import YamlSkillLoader  # noqa: F401

            with pytest.raises(ImportError, match="load_mcp_from_settings"):
                from cognitia.skills import load_mcp_from_settings  # noqa: F401

    def test_skills_star_import_skips_loader_helpers_when_loader_unavailable(self) -> None:
        """Star import should keep core skill symbols available without loader helper."""
        with _block_packages("cognitia.skills.loader"):
            for key in list(sys.modules):
                if key.startswith("cognitia.skills") and key != "cognitia.skills.loader":
                    del sys.modules[key]

            namespace: dict[str, Any] = {}
            exec("from cognitia.skills import *", namespace)

            assert "SkillRegistry" in namespace
            assert "YamlSkillLoader" not in namespace
            assert "load_mcp_from_settings" not in namespace

    def test_import_agent_module(self) -> None:
        """Agent facade imports without optional deps."""
        with _block_packages(
            "claude_agent_sdk", "anthropic", "langchain_core", "langchain_anthropic"
        ):
            for key in list(sys.modules):
                if key.startswith("cognitia.agent"):
                    del sys.modules[key]
            from cognitia.agent import Agent

            assert Agent is not None

    def test_block_packages_restores_cognitia_module_identity(self) -> None:
        """Isolation helper restores the original cognitia module objects."""
        from cognitia.memory_bank.types import MemoryBankViolation

        original = MemoryBankViolation

        with _block_packages("claude_agent_sdk"):
            for key in list(sys.modules):
                if key.startswith("cognitia.memory_bank"):
                    del sys.modules[key]
            from cognitia.memory_bank.types import MemoryBankViolation as reimported

            assert reimported is not original

        from cognitia.memory_bank.types import MemoryBankViolation as restored

        assert restored is original
