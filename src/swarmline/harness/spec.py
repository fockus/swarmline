"""HarnessSpec and sub-specs — single source of truth for agent composition.

harness-composition spec, Task 1 (REQ-001, REQ-010): a declarative,
frozen data model describing how an agent is assembled — kernel, optional
composition layer (supervisor/graph), optional infra (checkpoint/events/
replay), middleware, tools, and memory. Both the SDK builder and the YAML
loader (Tasks 2-3, not part of this module) compile into this same spec;
presets (Task 4) expand into it too.

graph-composition spec, Task 1 (REQ-001): ``CompositionSpec`` gains optional
declarative graph topology — ``edges`` (ordered role pairs), ``parallel``
(fan-out groups with a join target, :class:`ParallelSpec`), and ``routes``
(state-key routing rules, :class:`RouteSpec`) — every new field defaults to
an empty tuple, so any spec constructed the way it was before this
extension stays byte-identical in behavior. The ``"END"`` string is the
sentinel for "terminate the graph here" in ``edges``/``parallel``/``routes``
declarations; mapping it to ``workflow_graph.END_NODE`` is Task 3 territory,
not done here.

Pure domain layer: stdlib only (``dataclasses`` + ``__future__ annotations``
for forward-ref-friendly declaration order). No dependency on ``Agent``,
runtimes, or registries — those live in the application/infrastructure
layers that resolve this spec (Tasks 2-5). Every field is optional with a
default; the minimal ``HarnessSpec()`` is a solo ReAct kernel with no
composition or infra attached (REQ-008, REQ-009, REQ-010).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerSpec:
    """One worker slot inside a :class:`CompositionSpec`.

    Not defined in design.md's Interfaces section (only referenced by
    ``CompositionSpec.workers``) — this is a minimal, YAGNI-scoped
    definition covering exactly what a worker needs to be resolved: a role
    label, its own kernel (defaults to react, same as the top-level spec),
    and its own tool allowlist. Flagged as a design.md documentation gap /
    backlog candidate for Task 2+ to confirm before resolution logic lands.
    """

    role: str
    kernel: str = "react"
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteSpec:
    """One declarative state-key routing rule for graph composition.

    graph-composition spec, Task 1 (REQ-001). Read by the (not-yet-written,
    Task 3) graph adapter as: after *source* runs, look up ``state[key]`` in
    *mapping* (an ordered ``(value, target-role|"END")`` tuple, preserving
    YAML insertion order); fall back to *default* when the value has no
    entry. No callables — everything here is data, so it round-trips
    through YAML (design.md Decision 3).
    """

    source: str
    key: str
    mapping: tuple[tuple[str, str], ...]
    default: str | None = None


@dataclass(frozen=True)
class ParallelSpec:
    """One fan-out group for graph composition: parallel *members*, then *then*.

    graph-composition spec, Task 1 (REQ-001). *members* run concurrently off
    a shared upstream output; *then* is the join node that observes every
    member's output once all have completed (Task 3 adapter territory).
    """

    members: tuple[str, ...]
    then: str


@dataclass(frozen=True)
class CompositionSpec:
    """Optional multi-agent composition layer (supervisor or graph)."""

    mode: str
    workers: tuple[WorkerSpec, ...] = ()
    blackboard: bool = True
    edges: tuple[tuple[str, str], ...] = ()
    parallel: tuple[ParallelSpec, ...] = ()
    routes: tuple[RouteSpec, ...] = ()


@dataclass(frozen=True)
class InfraSpec:
    """Optional infrastructure layers — checkpointing, event recording, replay."""

    checkpoint: bool = False
    event_record: bool = False
    replay: bool = False


@dataclass(frozen=True)
class HarnessSpec:
    """Declarative, single-source-of-truth spec for building an agent.

    ``HarnessSpec()`` — the minimal, all-defaults spec — describes a solo
    ReAct kernel with no composition, no infra, and no preset (REQ-010).
    """

    kernel: str = "react"
    composition: CompositionSpec | None = None
    infra: InfraSpec | None = None
    middleware: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    memory: str | None = None
    preset: str | None = None
