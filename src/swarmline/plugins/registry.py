"""Plugin registry — discovers and loads plugins via entry points."""

from __future__ import annotations

import importlib
import sys
from typing import Any

from swarmline.plugins.types import PluginInfo, PluginType

# Entry point group name for Swarmline plugins
EP_GROUP = "swarmline.plugins"

# Sub-groups for typed discovery
EP_GROUPS = {
    PluginType.RUNTIME: "swarmline.runtimes",
    PluginType.MEMORY: "swarmline.memory_providers",
    PluginType.TOOL: "swarmline.tools",
    PluginType.SCORER: "swarmline.scorers",
}


def _entry_points(group: str) -> list[Any]:
    """Load entry points compatible with Python 3.10+."""
    if sys.version_info >= (3, 12):
        from importlib.metadata import entry_points

        return list(entry_points(group=group))
    else:
        from importlib.metadata import entry_points as _ep

        all_eps = _ep()
        if isinstance(all_eps, dict):
            return list(all_eps.get(group, []))
        return [ep for ep in all_eps if ep.group == group]


class PluginRegistry:
    """Discover and load Swarmline plugins via setuptools entry points."""

    @classmethod
    def discover(cls, plugin_type: PluginType | None = None) -> list[PluginInfo]:
        """Discover all installed plugins, optionally filtered by type."""
        plugins: list[PluginInfo] = []

        if plugin_type is not None:
            groups = {plugin_type: EP_GROUPS.get(plugin_type, EP_GROUP)}
        else:
            groups = dict(EP_GROUPS)
            groups[PluginType.UNKNOWN] = EP_GROUP

        for ptype, group in groups.items():
            for ep in _entry_points(group):
                plugins.append(PluginInfo(
                    name=ep.name,
                    module_path=ep.value,
                    plugin_type=ptype,
                    entry_point_group=group,
                ))

        # Deduplicate by name
        seen: set[str] = set()
        unique: list[PluginInfo] = []
        for p in plugins:
            if p.name not in seen:
                seen.add(p.name)
                unique.append(p)
        return unique

    @classmethod
    def load(cls, name: str, plugin_type: PluginType | None = None) -> Any:
        """Load a specific plugin by name. Returns the plugin object/class."""
        plugins = cls.discover(plugin_type)
        for p in plugins:
            if p.name == name:
                module_path, _, attr = p.module_path.rpartition(":")
                if not module_path:
                    module_path = p.module_path
                    attr = ""
                mod = importlib.import_module(module_path)
                if attr:
                    return getattr(mod, attr)
                return mod
        raise KeyError(f"Plugin '{name}' not found")

    @classmethod
    def get_info(cls, name: str) -> PluginInfo | None:
        """Get metadata for a specific plugin."""
        for p in cls.discover():
            if p.name == name:
                return p
        return None
