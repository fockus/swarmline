"""Unit: plugin registry — discovery, loading, type filtering."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from swarmline.plugins.registry import PluginRegistry
from swarmline.plugins.types import PluginInfo, PluginType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_ep(name: str, value: str, group: str = "swarmline.plugins") -> MagicMock:
    ep = MagicMock()
    ep.name = name
    ep.value = value
    ep.group = group
    return ep


# ---------------------------------------------------------------------------
# PluginInfo
# ---------------------------------------------------------------------------


class TestPluginInfo:

    def test_creation(self) -> None:
        info = PluginInfo(name="my-runtime", module_path="my_pkg:MyRuntime")
        assert info.name == "my-runtime"
        assert info.plugin_type == PluginType.UNKNOWN

    def test_with_type(self) -> None:
        info = PluginInfo(
            name="my-runtime",
            module_path="my_pkg:MyRuntime",
            plugin_type=PluginType.RUNTIME,
        )
        assert info.plugin_type == PluginType.RUNTIME

    def test_frozen(self) -> None:
        info = PluginInfo(name="x", module_path="y")
        with pytest.raises(AttributeError):
            info.name = "z"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PluginType
# ---------------------------------------------------------------------------


class TestPluginType:

    def test_values(self) -> None:
        assert PluginType.RUNTIME.value == "runtime"
        assert PluginType.MEMORY.value == "memory"
        assert PluginType.TOOL.value == "tool"
        assert PluginType.SCORER.value == "scorer"


# ---------------------------------------------------------------------------
# PluginRegistry.discover
# ---------------------------------------------------------------------------


class TestDiscover:

    @patch("swarmline.plugins.registry._entry_points")
    def test_discovers_from_entry_points(self, mock_eps: MagicMock) -> None:
        mock_eps.return_value = [
            _fake_ep("my-rt", "my_pkg:MyRuntime", "swarmline.runtimes"),
        ]
        plugins = PluginRegistry.discover(PluginType.RUNTIME)
        assert len(plugins) >= 1
        assert plugins[0].name == "my-rt"

    @patch("swarmline.plugins.registry._entry_points")
    def test_empty_when_no_plugins(self, mock_eps: MagicMock) -> None:
        mock_eps.return_value = []
        plugins = PluginRegistry.discover()
        assert plugins == []

    @patch("swarmline.plugins.registry._entry_points")
    def test_type_filter(self, mock_eps: MagicMock) -> None:
        mock_eps.return_value = [
            _fake_ep("scorer1", "pkg:Scorer1"),
        ]
        plugins = PluginRegistry.discover(PluginType.SCORER)
        assert all(p.plugin_type == PluginType.SCORER for p in plugins)


# ---------------------------------------------------------------------------
# PluginRegistry.load
# ---------------------------------------------------------------------------


class TestLoad:

    @patch("swarmline.plugins.registry._entry_points")
    def test_load_missing_raises(self, mock_eps: MagicMock) -> None:
        mock_eps.return_value = []
        with pytest.raises(KeyError, match="not found"):
            PluginRegistry.load("nonexistent")


# ---------------------------------------------------------------------------
# PluginRegistry.get_info
# ---------------------------------------------------------------------------


class TestGetInfo:

    @patch("swarmline.plugins.registry._entry_points")
    def test_get_info_returns_none_for_missing(self, mock_eps: MagicMock) -> None:
        mock_eps.return_value = []
        assert PluginRegistry.get_info("nonexistent") is None

    @patch("swarmline.plugins.registry._entry_points")
    def test_get_info_returns_plugin(self, mock_eps: MagicMock) -> None:
        mock_eps.return_value = [_fake_ep("my-tool", "pkg:Tool")]
        info = PluginRegistry.get_info("my-tool")
        assert info is not None
        assert info.name == "my-tool"
