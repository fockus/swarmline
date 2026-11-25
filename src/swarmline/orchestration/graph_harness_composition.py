"""Registers the "graph" composition block into the harness seam.

workflow-patterns spec, Task 3 (the FINAL task of the spec, closing
REQ-012/013/014/015/017/018). ``swarmline.harness.registries`` (harness-
composition spec, Task 2) defines a generic, process-wide "name -> zero-arg
resolver" seam for composition/infra blocks, and its own module docstring
explicitly sanctions wiring a block in from OUTSIDE by calling
``get_composition_registry().register(name, resolver)`` -- "without
touching this module or ``HarnessBuilder``". This module is exactly that
outside caller for the "graph" composition mode, mirroring
``swarmline.orchestration.supervisor.harness_composition``'s
``register_supervisor_composition`` (I-052) and
``swarmline.observability.harness_infra``'s ``register_observability_infra``
for the shape of the pattern.

Which existing substrate this hands back (REQ-012 -- zero new engine): the
registered resolver returns :class:`swarmline.orchestration.workflow_graph.
WorkflowGraph` itself -- the graph DSL class (``add_edge``/
``add_conditional_edge``/``add_parallel``, ``InMemoryCheckpoint``,
``WorkflowInterrupt``) that already backs graph-shaped workflows elsewhere
in the codebase (``orchestration/workflow_executor.py``,
``pipeline/bridge.py``, ``tests/unit/test_workflow_graph.py``). No new
engine/loop class is defined anywhere in this module -- the returned value
IS the pre-existing class object, not a wrapper or subclass of it. The two
other substrate primitives named in the spec --
``orchestration.supervisor.handoff.handoff`` (a thin wrapper already
driving ``multi_agent.graph_orchestrator.DefaultGraphOrchestrator.delegate``
/``.wait_for_task``) and ``DefaultGraphOrchestrator`` itself -- are the
task-delegation runtime UNDER a graph, whereas ``WorkflowGraph`` is the
composition DSL a "graph" mode most directly names (analogous to
``build_supervisor`` being the composition FACTORY for "supervisor" mode);
they remain available, unedited, for a future step to wire in without
requiring a second registration here.

Registration is an EXPLICIT function, never an import side-effect: importing
this module does nothing observable (no import-time dependency on
``swarmline.harness`` or ``swarmline.orchestration.workflow_graph`` at all
-- see ``register_graph_composition`` below). A bootstrap layer calls
``register_graph_composition()`` once, early, to make ``"graph"``
resolvable through the harness composition seam. Side-effect-on-import
registration would make availability depend on unpredictable import order
across the codebase, which is exactly the non-determinism this module
avoids by requiring an explicit call.

Honest scope (existence-validation only, matching observability's infra
blocks and the sibling supervisor block): today,
``HarnessBuilder.build()`` (harness/builder.py) resolves ``composition.mode``
by calling ``get_composition_registry().get(mode)`` and DISCARDS the
returned value -- it only proves the block EXISTS, it does not yet thread
runtime state (nodes, edges, a checkpoint store) into a live graph
execution. So once ``register_graph_composition()`` has been called, a
``graph``-composition spec's ``.build()`` SUCCEEDS instead of raising
``CompositionBlockNotFound`` -- but the returned ``Agent`` is still the
kernel-only agent ``build()`` always produces, not yet a live
graph-composed one. Making ``build()`` actually APPLY the composition
(construct a ``WorkflowGraph`` from ``CompositionSpec.workers`` and drive it)
is a separate, larger follow-up -- folds into the same I-066 class of work
already flagged by the supervisor block's own docstring.

Import-light (the precise guarantee, I-020): this module has NO module-level
import of ``swarmline.harness`` or ``swarmline.orchestration.workflow_graph``.
``get_composition_registry`` is imported lazily INSIDE
``register_graph_composition`` (so calling it imports
``swarmline.harness.registries`` -- a light module). ``WorkflowGraph``
(whose import chain never touches ``swarmline.multi_agent.*`` -- verified:
``swarmline.orchestration.workflow_graph`` imports only stdlib) is deferred
one level further, INSIDE the registered resolver, so it is imported only
when the ``"graph"`` block is actually RESOLVED
(``get_composition_registry().get("graph")``, which ``build()`` does),
never merely by importing this module or calling the registration function.
This keeps the stronger promise the spec asks for: ``swarmline.multi_agent.
graph_orchestrator`` (which eagerly pulls ThinRuntime the moment
``swarmline/multi_agent/__init__.py`` runs) is never imported at all by
registering or merely importing this module -- resolving "graph" does not
even need it, since ``WorkflowGraph`` alone satisfies the handle.

workflow-patterns spec, Task 3 -- reconciliation with Task 1's I-052
precedent (module-name deviation, documented here on the user's explicit
direction, same reasoning as
``orchestration/supervisor/harness_composition.py``'s own reconciliation
note): ``tasks.md`` planned extending a single NEW module,
``orchestration/harness_compositions.py`` with a shared
``register_workflow_compositions()`` registering both "supervisor" and
"graph". That module was never created (Task 1 kept
``register_supervisor_composition`` in the pre-existing I-052 module
instead of creating it). Task 3 follows the SAME precedent: rather than
retrofit a shared module that still does not exist, "graph" gets its own
sibling module + its own explicit registration function
(``register_graph_composition``), one responsibility per module -- mirroring
both the supervisor block and ``observability/harness_infra.py``'s
``register_observability_infra``. REQ-014/REQ-015/REQ-018 are guard
invariants with no work-item by construction (nothing in this task touches
``swarmline/pipeline/``, adds a ``HarnessSpec`` field, or registers a new
kernel) -- closed by the diff-scope proof in this task's closing report,
not by anything in this module's code.
"""

from __future__ import annotations


def register_graph_composition() -> None:
    """Register the ``"graph"`` composition-block resolver.

    workflow-patterns spec, Task 3 (REQ-012/013). Idempotent: if ``"graph"``
    is already registered, this is a no-op -- it does NOT overwrite the
    existing resolver with a fresh one. Presence is checked via the
    registry's own public ``names()`` (no private attribute access; mirrors
    ``register_supervisor_composition``/``register_observability_infra``/
    ``KernelRegistry``'s ``register``/``get``/``names`` shape).

    The registered resolver is a zero-arg callable that returns
    :class:`swarmline.orchestration.workflow_graph.WorkflowGraph` -- the
    EXISTING graph DSL class itself (see this module's docstring for why
    this is zero-new-engine), not an already-built graph instance.
    ``HarnessBuilder.build()`` currently only calls the resolver to prove
    the block exists and discards the result (see this module's docstring);
    a future "build() applies composition" step would instead use the
    returned class to construct and drive a real graph-composed ``Agent``
    from ``CompositionSpec.workers``.
    """
    from swarmline.harness.registries import get_composition_registry

    registry = get_composition_registry()
    if "graph" in registry.names():
        return

    def _resolve_graph_factory() -> object:
        from swarmline.orchestration.workflow_graph import WorkflowGraph

        return WorkflowGraph

    registry.register("graph", _resolve_graph_factory)
