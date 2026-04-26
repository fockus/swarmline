"""Tests for RuntimeRegistry - extensible adapter registry."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from swarmline.runtime.capabilities import RuntimeCapabilities
from swarmline.runtime.types import RuntimeConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dummy_factory(config: RuntimeConfig, **kwargs: Any) -> object:
    """Dummy factory for testing."""
    return MagicMock(name="dummy_runtime")


def _dummy_capabilities() -> RuntimeCapabilities:
    return RuntimeCapabilities(runtime_name="custom", tier="light")


# ---------------------------------------------------------------------------
# RuntimeRegistry — core operations
# ---------------------------------------------------------------------------


class TestRuntimeRegistryCore:
    """RuntimeRegistry — register, get, unregister, list."""

    def test_register_and_get_returns_factory(self) -> None:
        """register() stores factory, get() retrieves it."""
        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        registry.register("custom", _dummy_factory)
        assert registry.get("custom") is _dummy_factory

    def test_register_overwrites_existing(self) -> None:
        """Re-register same name overwrites previous factory."""
        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        factory_a = MagicMock()
        factory_b = MagicMock()
        registry.register("custom", factory_a)
        registry.register("custom", factory_b)
        assert registry.get("custom") is factory_b

    def test_unregister_removes_runtime(self) -> None:
        """unregister() removes runtime, get() returns None."""
        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        registry.register("custom", _dummy_factory)
        result = registry.unregister("custom")
        assert result is True
        assert registry.get("custom") is None

    def test_unregister_nonexistent_returns_false(self) -> None:
        """unregister() on unknown name returns False."""
        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        assert registry.unregister("nonexistent") is False

    def test_get_nonexistent_returns_none(self) -> None:
        """get() for unknown name returns None."""
        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        assert registry.get("unknown") is None

    def test_is_registered_true_for_known(self) -> None:
        """is_registered() returns True for registered runtime."""
        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        registry.register("custom", _dummy_factory)
        assert registry.is_registered("custom") is True

    def test_is_registered_false_for_unknown(self) -> None:
        """is_registered() returns False for unknown runtime."""
        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        assert registry.is_registered("unknown") is False


class TestRuntimeRegistryCapabilities:
    """RuntimeRegistry — capabilities management."""

    def test_get_capabilities_returns_registered(self) -> None:
        """get_capabilities() returns capabilities passed during register."""
        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        caps = _dummy_capabilities()
        registry.register("custom", _dummy_factory, capabilities=caps)
        assert registry.get_capabilities("custom") is caps

    def test_get_capabilities_none_when_not_provided(self) -> None:
        """get_capabilities() returns None if no capabilities registered."""
        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        registry.register("custom", _dummy_factory)
        assert registry.get_capabilities("custom") is None

    def test_get_capabilities_unknown_returns_none(self) -> None:
        """get_capabilities() returns None for unknown runtime."""
        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        assert registry.get_capabilities("unknown") is None


# ---------------------------------------------------------------------------
# Built-in runtimes
# ---------------------------------------------------------------------------


class TestBuiltinRegistration:
    """Built-in runtimes auto-registered in default registry."""

    def test_list_available_includes_builtins(self) -> None:
        """Default registry includes all public builtins and internal headless mode."""
        from swarmline.runtime.registry import get_default_registry

        registry = get_default_registry()
        available = registry.list_available()
        for name in (
            "claude_sdk",
            "deepagents",
            "thin",
            "cli",
            "openai_agents",
            "pi_sdk",
            "headless",
        ):
            assert name in available

    def test_is_registered_builtins(self) -> None:
        """All builtins are registered."""
        from swarmline.runtime.registry import get_default_registry

        registry = get_default_registry()
        for name in (
            "claude_sdk",
            "deepagents",
            "thin",
            "cli",
            "openai_agents",
            "pi_sdk",
            "headless",
        ):
            assert registry.is_registered(name)

    def test_get_capabilities_builtins(self) -> None:
        """Builtins have capabilities registered."""
        from swarmline.runtime.registry import get_default_registry

        registry = get_default_registry()
        for name in (
            "claude_sdk",
            "deepagents",
            "thin",
            "cli",
            "openai_agents",
            "pi_sdk",
            "headless",
        ):
            caps = registry.get_capabilities(name)
            assert caps is not None
            assert caps.runtime_name == name


# ---------------------------------------------------------------------------
# Custom runtime registration
# ---------------------------------------------------------------------------


class TestCustomRuntimeRegistration:
    """Custom runtime registration and validation."""

    def test_custom_runtime_register_and_list(self) -> None:
        """Custom runtime appears in list_available()."""
        from swarmline.runtime.registry import get_default_registry

        registry = get_default_registry()
        registry.register("my_custom", _dummy_factory)
        assert "my_custom" in registry.list_available()
        # Cleanup
        registry.unregister("my_custom")

    def test_custom_runtime_in_valid_names(self) -> None:
        """Registered custom runtime passes RuntimeConfig validation."""
        from swarmline.runtime.registry import (
            get_default_registry,
            get_valid_runtime_names,
        )

        registry = get_default_registry()
        caps = RuntimeCapabilities(runtime_name="my_rt", tier="light")
        registry.register("my_rt", _dummy_factory, capabilities=caps)
        try:
            valid = get_valid_runtime_names()
            assert "my_rt" in valid
            # RuntimeConfig should accept it
            config = RuntimeConfig(runtime_name="my_rt")
            assert config.runtime_name == "my_rt"
        finally:
            registry.unregister("my_rt")


# ---------------------------------------------------------------------------
# Factory integration
# ---------------------------------------------------------------------------


class TestFactoryUsesRegistry:
    """RuntimeFactory uses registry for runtime creation."""

    def test_factory_uses_registry(self) -> None:
        """RuntimeFactory(registry=...) delegates create to registry."""
        from swarmline.runtime.factory import RuntimeFactory
        from swarmline.runtime.registry import RuntimeRegistry

        mock_runtime = MagicMock()
        mock_factory_fn = MagicMock(return_value=mock_runtime)

        registry = RuntimeRegistry()
        caps = RuntimeCapabilities(runtime_name="test_rt", tier="light")
        registry.register("test_rt", mock_factory_fn, capabilities=caps)

        factory = RuntimeFactory(registry=registry)
        cfg = RuntimeConfig.__new__(RuntimeConfig)
        object.__setattr__(cfg, "runtime_name", "test_rt")
        object.__setattr__(cfg, "feature_mode", "portable")
        object.__setattr__(cfg, "required_capabilities", None)
        object.__setattr__(cfg, "output_type", None)
        object.__setattr__(cfg, "output_format", None)
        object.__setattr__(cfg, "max_iterations", 6)
        object.__setattr__(cfg, "max_tool_calls", 8)
        object.__setattr__(cfg, "max_model_retries", 2)
        object.__setattr__(cfg, "model", "claude-sonnet-4-20250514")
        object.__setattr__(cfg, "base_url", None)
        object.__setattr__(cfg, "extra", {})
        object.__setattr__(cfg, "allow_native_features", False)
        object.__setattr__(cfg, "native_config", {})

        runtime = factory.create(config=cfg)
        mock_factory_fn.assert_called_once()
        assert runtime is mock_runtime

    def test_factory_backward_compat_no_registry(self) -> None:
        """RuntimeFactory() without explicit registry still works."""
        from swarmline.runtime.factory import RuntimeFactory

        factory = RuntimeFactory()
        # Should resolve runtime name without error
        name = factory.resolve_runtime_name()
        assert name == "claude_sdk"
        # create should work (may return _ErrorRuntime if deps missing, but no crash)
        runtime = factory.create()
        assert runtime is not None


# ---------------------------------------------------------------------------
# Entry points discovery
# ---------------------------------------------------------------------------


class TestEntryPointsDiscovery:
    """Entry point plugin discovery."""

    def test_entry_points_discovery_registers_runtime(self) -> None:
        """Mock entry point is auto-discovered and registered."""
        from swarmline.runtime.registry import RuntimeRegistry, _discover_entry_points

        mock_runtime_fn = MagicMock()
        mock_caps = RuntimeCapabilities(runtime_name="plugin_rt", tier="light")

        mock_ep = MagicMock()
        mock_ep.name = "plugin_rt"
        mock_ep.load.return_value = (mock_runtime_fn, mock_caps)

        registry = RuntimeRegistry()
        with patch(
            "swarmline.runtime.registry.entry_points",
            return_value=[mock_ep],
        ):
            _discover_entry_points(registry)

        assert registry.is_registered("plugin_rt")
        assert registry.get("plugin_rt") is mock_runtime_fn
        assert registry.get_capabilities("plugin_rt") is mock_caps

    def test_entry_points_bad_plugin_skipped(self) -> None:
        """Bad entry point (raises on load) is skipped silently."""
        from swarmline.runtime.registry import RuntimeRegistry, _discover_entry_points

        mock_ep = MagicMock()
        mock_ep.name = "bad_plugin"
        mock_ep.load.side_effect = ImportError("missing dep")

        registry = RuntimeRegistry()
        with patch(
            "swarmline.runtime.registry.entry_points",
            return_value=[mock_ep],
        ):
            _discover_entry_points(registry)

        assert not registry.is_registered("bad_plugin")

    def test_entry_points_bad_return_format_skipped(self) -> None:
        """Entry point returning wrong format is skipped."""
        from swarmline.runtime.registry import RuntimeRegistry, _discover_entry_points

        mock_ep = MagicMock()
        mock_ep.name = "bad_format"
        mock_ep.load.return_value = "not a tuple"

        registry = RuntimeRegistry()
        with patch(
            "swarmline.runtime.registry.entry_points",
            return_value=[mock_ep],
        ):
            _discover_entry_points(registry)

        assert not registry.is_registered("bad_format")


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Registry is thread-safe."""

    def test_concurrent_register_no_crash(self) -> None:
        """Concurrent register calls don't crash."""
        import threading

        from swarmline.runtime.registry import RuntimeRegistry

        registry = RuntimeRegistry()
        errors: list[Exception] = []

        def register_many(prefix: str) -> None:
            try:
                for i in range(50):
                    registry.register(f"{prefix}_{i}", _dummy_factory)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_many, args=(f"t{t}",)) for t in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(registry.list_available()) == 200
