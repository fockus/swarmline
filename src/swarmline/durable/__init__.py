"""Durable execution — native, provider-agnostic durability (0 new deps).

``DurableRuntime`` decorates any ``AgentRuntime`` and checkpoints
conversation state after each observable step boundary into a B1
``Checkpointer`` (``swarmline.protocols.checkpoint``). Three LangGraph-parity
modes: ``exit`` (terminal-only), ``async`` (background checkpoint), ``sync``
(awaited checkpoint) — see ``DurabilityConfig``/``DurabilityMode``.

Vendor durable-agent backends (``DbosDurableRuntime``, ``PrefectDurableRuntime``)
are optional extras, lazily imported on first access (``_OPTIONAL_EXPORTS``
below, landing in Stage C1.5) — install ``swarmline[dbos]`` / ``swarmline[prefect]``.

Temporal is deliberately NOT in this lazy map: Temporal-grade durability is
already served by the native ``swarmline.runtime.temporal`` runtime
(``runtime="temporal"`` — workflow + activities, durable HITL, reattach,
worker CLI). A thin ``TemporalDurableRuntime`` wrapper here would duplicate
that (see the plan's "Scope review 2026-07-04" for the decision record).
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from swarmline.durable.config import DurabilityConfig, DurabilityMode
from swarmline.durable.runtime import DurableRuntime
from swarmline.durable.time_travel import fork, get_state_history

__all__ = [
    "DurabilityConfig",
    "DurabilityMode",
    "DurableRuntime",
    "fork",
    "get_state_history",
]

_OPTIONAL_EXPORTS: dict[str, tuple[str, str, str]] = {
    "DbosDurableRuntime": (
        "swarmline.durable.dbos",
        "DbosDurableRuntime",
        "Install `swarmline[dbos]` to use DbosDurableRuntime.",
    ),
    "PrefectDurableRuntime": (
        "swarmline.durable.prefect",
        "PrefectDurableRuntime",
        "Install `swarmline[prefect]` to use PrefectDurableRuntime.",
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
