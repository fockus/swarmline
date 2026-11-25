"""Composable agent harness — domain foundation.

harness-composition spec, Task 1 (REQ-001, REQ-010). Re-exports the four
frozen dataclasses that form the single source of truth for describing an
agent's composition: :class:`HarnessSpec`, :class:`CompositionSpec`,
:class:`InfraSpec`, :class:`WorkerSpec`.

graph-composition spec, Task 1 (REQ-001): also re-exports
:class:`RouteSpec`/:class:`ParallelSpec` — the two sub-specs backing
``CompositionSpec``'s declarative graph topology (``edges``/``parallel``/
``routes``) — so fluent ``.graph()`` callers can build them without
reaching into the ``spec`` submodule directly.

Pure data package — importing it pulls in only stdlib. The SDK builder,
YAML loader, preset registry, and registry-based resolution to a concrete
``Agent`` are separate, additive layers (Tasks 2-5), not part of this
package's import surface.
"""

from __future__ import annotations

from swarmline.harness.spec import (
    CompositionSpec,
    HarnessSpec,
    InfraSpec,
    ParallelSpec,
    RouteSpec,
    WorkerSpec,
)

__all__ = [
    "CompositionSpec",
    "HarnessSpec",
    "InfraSpec",
    "ParallelSpec",
    "RouteSpec",
    "WorkerSpec",
]
