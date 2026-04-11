"""Plugin system types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PluginType(str, Enum):
    """Category of a Swarmline plugin."""

    RUNTIME = "runtime"
    MEMORY = "memory"
    TOOL = "tool"
    SCORER = "scorer"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PluginInfo:
    """Metadata about a discovered plugin."""

    name: str
    module_path: str
    plugin_type: PluginType = PluginType.UNKNOWN
    version: str = ""
    description: str = ""
    entry_point_group: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
