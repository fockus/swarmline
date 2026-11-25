"""HarnessBuilder — fluent SDK front-end compiling ``HarnessSpec`` -> ``Agent``.

harness-composition spec, Task 2 (REQ-002, REQ-004, REQ-008, REQ-009,
REQ-012). ``HarnessBuilder`` accumulates a frozen
:class:`~swarmline.harness.spec.HarnessSpec` — the single source of truth —
and, on :meth:`HarnessBuilder.build`, resolves it into the EXISTING
:class:`swarmline.agent.Agent`: kernel through the H1 ``KernelRegistry``,
composition/infra through the thin registry seam in
:mod:`swarmline.harness.registries`.

Scope boundary: infra (checkpoint/event-record/replay) blocks are NOT wired
to any concrete implementation here (the observability-events block is an
unwritten spec). ``composition=None``/``infra=None`` (the common, minimal
path) resolves to nothing, at zero cost (REQ-008/009). An infra flag that IS
requested but not (yet) registered raises a clear, named error.

I-066: the ``"supervisor"`` composition mode IS applied (not just
existence-validated) — :meth:`HarnessBuilder.build` calls the resolved
factory (``build_supervisor``) with a fresh ``SupervisorState``/
``ThinSubagentOrchestrator`` pair, returning an ``Agent`` driven by the
assembled 5-tool supervisor surface — see
:func:`swarmline.harness.agent_assembly.build_supervisor_agent`.
graph-composition spec, Task 3: ``"graph"`` is ALSO applied the same way —
see :func:`swarmline.harness.graph_assembly.build_graph_agent`, which
compiles the declared/default topology onto a real ``WorkflowGraph`` and
returns an ``Agent`` that executes it. Every OTHER (unrecognized-but-
registered) mode keeps the existence-validation-only behavior: the
resolved factory falls out of scope, unused.

``AgentConfig`` has no field selecting the thin-runtime execution mode
(``ThinRuntime.run`` takes ``mode_hint`` as a call-time kwarg) — so a bare
``Agent(AgentConfig(runtime="thin"))`` always resolves to "conversational",
never ``spec.kernel``. To make ``spec.kernel`` drive the built ``Agent``
(REQ-002), :meth:`HarnessBuilder.build` injects a
:class:`~swarmline.harness.agent_assembly._ModeHintRuntimeFactory` through
``Agent``'s sanctioned ``runtime_factory`` extension point — a decorator
pinning ``mode_hint=spec.kernel`` on every ``run()``. Purely additive.

I-076: the runtime-factory decorators and the supervisor-apply
construction logic live in :mod:`swarmline.harness.agent_assembly`
(split out to stay under the SRP line-count ceiling); this module keeps
the fluent builder plus ALL validation/registry-consultation logic.

Import-light: every ``swarmline``-internal name outside this package is
imported lazily, inside method bodies (``agent_assembly`` is imported at
module level — it is itself import-light, see its own module docstring).
The supervisor-apply imports are confined INSIDE
:func:`~swarmline.harness.agent_assembly.build_supervisor_agent`
specifically (not merely inside ``build()``) so a non-supervisor
``build()`` call never pulls them.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from swarmline.harness.agent_assembly import (
    _DEFAULT_SYSTEM_PROMPT,
    _ModeHintRuntimeFactory,
    build_supervisor_agent,
)
from swarmline.harness.registries import get_composition_registry, get_infra_registry
from swarmline.harness.spec import (
    CompositionSpec,
    HarnessSpec,
    InfraSpec,
    ParallelSpec,
    RouteSpec,
    WorkerSpec,
)

if TYPE_CHECKING:
    from swarmline.agent import Agent


class HarnessBuilder:
    """Fluent SDK front-end. Accumulates a :class:`HarnessSpec`; ``build()`` resolves it.

    Mutable by design: each fluent method mutates the builder's internal
    spec (via ``dataclasses.replace``, since ``HarnessSpec`` itself stays
    frozen) and returns ``self``, so calls chain naturally. The frozen
    ``HarnessSpec`` — not the builder — is the single source of truth
    (design.md ADR).
    """

    def __init__(self, spec: HarnessSpec | None = None) -> None:
        self._spec = spec if spec is not None else HarnessSpec()

    @classmethod
    def from_spec(cls, spec: HarnessSpec) -> HarnessBuilder:
        """Wrap an existing spec (used by YAML/preset front-ends, Tasks 3-4)."""
        return cls(spec)

    @property
    def spec(self) -> HarnessSpec:
        """The accumulated spec, as it stands right now (read-only snapshot)."""
        return self._spec

    def kernel(self, name: str) -> HarnessBuilder:
        """Set the execution kernel mode (resolved via ``KernelRegistry`` in ``build()``)."""
        self._spec = replace(self._spec, kernel=name)
        return self

    def supervisor(
        self,
        workers: tuple[WorkerSpec, ...] = (),
        *,
        blackboard: bool = True,
    ) -> HarnessBuilder:
        """Attach a supervisor composition layer over *workers*.

        Resolved (or rejected with a named error — see module docstring's
        scope boundary) via the composition registry seam in ``build()``.
        """
        self._spec = replace(
            self._spec,
            composition=CompositionSpec(
                mode="supervisor", workers=tuple(workers), blackboard=blackboard
            ),
        )
        return self

    def graph(
        self,
        workers: tuple[WorkerSpec, ...] = (),
        *,
        edges: tuple[tuple[str, str], ...] = (),
        parallel: tuple[ParallelSpec, ...] = (),
        routes: tuple[RouteSpec, ...] = (),
    ) -> HarnessBuilder:
        """Attach a graph composition layer over *workers* with declarative topology.

        graph-composition spec, Task 1 (REQ-002). Mirrors :meth:`supervisor`:
        sets ``mode="graph"`` plus the declared topology on the accumulated
        spec. Resolved (or rejected with a named error) via the composition
        registry seam in ``build()`` — actually APPLYING graph mode (walking
        ``edges``/``parallel``/``routes`` into a live ``WorkflowGraph``) is
        Task 2/3 territory, out of scope here.

        Unlike ``supervisor()``, ``graph()`` takes no ``blackboard``
        parameter (design decision — graph state flows through the declared
        edges/routes, not a shared blackboard).

        *edges*/*parallel*/*routes* elements may be plain tuples/lists
        (``edges``) or already-built :class:`ParallelSpec`/:class:`RouteSpec`
        instances (``parallel``/``routes``); each is normalized into the
        frozen tuple shape ``CompositionSpec`` expects.
        """
        self._spec = replace(
            self._spec,
            composition=CompositionSpec(
                mode="graph",
                workers=tuple(workers),
                edges=tuple(tuple(edge) for edge in edges),
                parallel=tuple(parallel),
                routes=tuple(routes),
            ),
        )
        return self

    def with_checkpointing(self) -> HarnessBuilder:
        """Enable the checkpoint infra flag (merges into any existing ``InfraSpec``)."""
        current = self._spec.infra or InfraSpec()
        self._spec = replace(self._spec, infra=replace(current, checkpoint=True))
        return self

    def with_events(self) -> HarnessBuilder:
        """Enable the event-record infra flag (merges into any existing ``InfraSpec``)."""
        current = self._spec.infra or InfraSpec()
        self._spec = replace(self._spec, infra=replace(current, event_record=True))
        return self

    def build(self) -> Agent:
        """Resolve the accumulated spec through the registries and return an ``Agent``.

        - Kernel: validated against the LIVE H1 ``KernelRegistry`` (REQ-002)
          — an unregistered mode raises ``KernelNotFound``.
        - Preset (REQ-003): if ``spec.preset`` names a preset, resolved via
          ``PresetRegistry`` (unknown name -> ``PresetNotFound``). Does NOT
          expand/merge — only guards a silently ignored typo.
        - Composition / infra: resolved through the registry seam in
          ``swarmline.harness.registries``; ``None`` = zero overhead
          (REQ-008/009), unregistered -> a named error. Infra validates
          BEFORE composition so it's never skipped by the supervisor/graph
          early-returns below. Worker ``kernel``s validated too. I-066:
          ``composition.mode == "supervisor"`` is APPLIED — see
          :func:`~swarmline.harness.agent_assembly.build_supervisor_agent`.
          graph-composition spec, Task 3: ``mode == "graph"`` is ALSO
          APPLIED — see :func:`~swarmline.harness.graph_validation.validate_graph_topology`
          (run right after the worker-kernel loop, REQ-010..014/019/020)
          then :func:`~swarmline.harness.graph_assembly.build_graph_agent`.
          Every OTHER (unrecognized-but-registered) mode stays existence-
          validation-only (factory resolved then discarded).
        - Returns the EXISTING ``Agent`` interface (REQ-012), kernel pinned
          via ``_ModeHintRuntimeFactory`` — or ``_SupervisorRuntimeFactory``/
          the graph-composed runtime for an applied supervisor/graph
          composition (adds the tool surface / runs the topology).

        See also :func:`swarmline.harness.validation.validate_harness_spec`.
        """
        from swarmline.runtime.thin.kernels import get_default_kernel_registry
        from swarmline.runtime.thin.kernels.errors import KernelNotFound

        kernel_registry = get_default_kernel_registry()
        if self._spec.kernel not in kernel_registry.modes():
            raise KernelNotFound(self._spec.kernel, kernel_registry.modes())

        if self._spec.preset is not None:
            from swarmline.harness.presets import get_preset_registry

            get_preset_registry().expand(self._spec.preset)

        composition_factory: Any = None
        if self._spec.composition is not None:
            composition_factory = get_composition_registry().get(
                self._spec.composition.mode
            )
            for worker in self._spec.composition.workers:
                if worker.kernel not in kernel_registry.modes():
                    raise KernelNotFound(worker.kernel, kernel_registry.modes())
            if self._spec.composition.mode == "graph":
                from swarmline.harness.graph_validation import validate_graph_topology

                validate_graph_topology(self._spec.composition)

        if self._spec.infra is not None:
            infra_registry = get_infra_registry()
            for block_name, enabled in (
                ("checkpoint", self._spec.infra.checkpoint),
                ("event_record", self._spec.infra.event_record),
                ("replay", self._spec.infra.replay),
            ):
                if enabled:
                    infra_registry.get(block_name)

        # I-066 / graph-composition Task 3: infra is validated above so it's
        # never skipped by either early return; "supervisor" and "graph"
        # are APPLIED, every other (unrecognized-but-registered) mode still
        # discards the factory (unchanged).
        if getattr(self._spec.composition, "mode", None) == "supervisor":
            return build_supervisor_agent(self._spec, composition_factory)

        if getattr(self._spec.composition, "mode", None) == "graph":
            from swarmline.harness.graph_assembly import build_graph_agent

            return build_graph_agent(self._spec, composition_factory)

        from swarmline.agent import Agent, AgentConfig

        config = AgentConfig(
            system_prompt=_DEFAULT_SYSTEM_PROMPT,
            runtime="thin",
            native_config={"harness_kernel": self._spec.kernel},
        )
        return Agent(config, runtime_factory=_ModeHintRuntimeFactory(self._spec.kernel))
