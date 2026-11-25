"""Control-flow value objects for the native Graph DSL (Epic D, Stage D1.2).

`Command` lets a node merge `update` into state AND route to `goto` in one
return value: `goto=END` ends the run, `goto=[Send(...)]` fans out to
parallel branches (wired up in a later stage), `goto=None` falls back to
the graph's static/conditional edges. `START` / `END` are unique sentinel
objects (not bare strings) whose `.value` interops with the string-keyed
`orchestration.workflow_graph` engine (`END.value == workflow_graph.END_NODE`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from swarmline.errors import SwarmlineError


class _Sentinel:
    """A unique, identity-comparable marker with a stable string `.value`."""

    __slots__ = ("_label", "value")

    def __init__(self, label: str, value: str) -> None:
        self._label = label
        self.value = value

    def __repr__(self) -> str:
        return f"<{self._label}>"


START = _Sentinel("START", "__start__")
END = _Sentinel("END", "__end__")


@dataclass(frozen=True)
class Send:
    """A single fan-out unit: route `payload` to a fresh invocation of `node`."""

    node: str
    payload: Any


@dataclass(frozen=True)
class Command:
    """A node's combined state-update + routing directive.

    `update`, when set, is merged into graph state via the declared channel
    reducers (same as a plain dict return). `goto` selects the next node(s):
    a node name, `END`, a list of `Send` for fan-out, or `None` to defer to
    the graph's static/conditional edges.
    """

    update: Mapping[str, Any] | None = None
    goto: str | _Sentinel | Sequence[str | Send] | None = None


class GraphConfigError(SwarmlineError):
    """Raised for build-time graph misconfiguration (bad nodes/edges/schema)."""


class GraphRecursionError(SwarmlineError):
    """Raised at runtime when a graph run exceeds its `recursion_limit`."""


__all__ = [
    "END",
    "START",
    "Command",
    "GraphConfigError",
    "GraphRecursionError",
    "Send",
]
