"""Swarmline Plugin System — entry-point-based discovery and loading."""

from __future__ import annotations

from swarmline.plugins.runner import PluginRunner, SubprocessPluginRunner
from swarmline.plugins.runner_types import PluginHandle, PluginManifest, PluginState

__all__ = [
    "PluginHandle",
    "PluginManifest",
    "PluginRunner",
    "PluginState",
    "SubprocessPluginRunner",
]
