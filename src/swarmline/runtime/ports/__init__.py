"""Ports package.

.. warning:: EXPERIMENTAL — this layer is not on the ``Agent`` production
   path and is excluded from the runtime-parity obligations of
   the runtime-parity plan (open question 2 resolved 2026-07-04:
   marked experimental; removal in favor of dispatch-level filters is a
   separate future decision, tracked in the Memory Bank backlog).
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from swarmline.runtime.ports.base import (
    HISTORY_MAX,
    BaseRuntimePort,
    StreamEvent,
    convert_event,
)

__all__ = [
    "HISTORY_MAX",
    "BaseRuntimePort",
    "StreamEvent",
    "convert_event",
]

_OPTIONAL_EXPORTS: dict[str, tuple[str, str, str]] = {
    "DeepAgentsRuntimePort": (
        "swarmline.runtime.ports.deepagents",
        "DeepAgentsRuntimePort",
        "Install optional deepagents dependencies to use DeepAgentsRuntimePort.",
    ),
    "ThinRuntimePort": (
        "swarmline.runtime.ports.thin",
        "ThinRuntimePort",
        "Install optional thin runtime dependencies to use ThinRuntimePort.",
    ),
}


def __getattr__(name: str) -> Any:
    optional = _OPTIONAL_EXPORTS.get(name)
    if optional is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name, hint = optional
    try:
        module = import_module(module_name)
        value = getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        raise ImportError(f"{attr_name} is unavailable. {hint}") from exc

    globals()[name] = value
    return value
