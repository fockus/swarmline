"""Graph-composition apply: ``build()`` -> a LIVE, graph-composed Agent.

graph-composition spec, Tasks 3-4 (REQ-004..009, REQ-015..017). Tasks 1-2
gave ``CompositionSpec`` a declarative topology (``edges``/``parallel``/
``routes``) and a fail-loud validator (``graph_validation.validate_graph_
topology``) that ``builder.py`` runs BEFORE ever reaching this module. This
module is the part that actually APPLIES a validated ``mode="graph"``
composition: :func:`build_graph_agent` wraps the compiled topology behind
the standard ``Agent`` facade.

The per-node runner and the topology-to-``WorkflowGraph`` compiler
(:func:`~swarmline.harness.graph_compile.compile_graph`, including Task 4's
``RouteSpec`` -> ``ConditionFn`` compilation) live in
``harness/graph_compile.py`` (judge-advisory carve-out from Task 3's own
review: this module was sitting at exactly the 400-line NFR-004 ceiling,
with no room left for Task 4's routing work). Import direction is
one-way: this module imports FROM ``graph_compile``, never the reverse.

Architecture (design.md):

    HarnessBuilder.build()  [mode == "graph", already topology-validated]
      -> build_graph_agent(spec, composition_factory)
           composition_factory = the resolved "graph" registry factory,
           i.e. the ``WorkflowGraph`` class itself (uninvoked) -- see
           ``orchestration/graph_harness_composition.py``.
      -> Agent(config, runtime_factory=_GraphRuntimeFactory(spec, composition_factory))
      -> Agent.query()/stream() -> run_portable_runtime -> factory.create()
      -> _GraphAgentRuntime.run(messages, system_prompt, active_tools, ...):
           1. seed: state = {"input": <last user message>, "outputs": {}}
           2. compile: ``graph_compile.compile_graph`` (per-node runner
              closures) + declared/default edges + add_parallel + routes
              (Task 4, compiled to conditional edges) -- returns
              ``(graph, node_runners)`` so this module owns the exact
              role -> runner-closure mapping the graph itself holds.
           3. execute: ``graph.execute(state, node_interceptor=...)`` as an
              ``asyncio.Task`` (Task 5, REQ-008): the interceptor is the
              substrate's OWN documented hook (``WorkflowGraph.
              _execute_node`` hands full responsibility for running a node
              to the interceptor once one is supplied) -- ours does
              ``queue.put_nowait(("started", role)); result = await
              node_runners[role](state); queue.put_nowait(("finished",
              role))`` and returns *result* unchanged, so the graph's own
              execution semantics (including parallel-group member
              concurrency) are untouched. ``run()`` drains the queue with
              ``await queue.get()`` and yields one progress
              ``RuntimeEvent`` (``type="status"``, ``data={"role":
              ..., "phase": "started"|"finished", "text": ...}``) per item
              WHILE the graph task is still executing -- not batched
              post-hoc -- until a sentinel (queued from the task's own
              ``finally``, so it is queued on EVERY exit path: success,
              node failure, route-miss, or cancellation) tells it to stop.
           4. final: RuntimeEvent.final(text=<the node that ACTUALLY ran
              last>, native_metadata={"graph_state": state}) -- REQ-006/007,
              existing keys byte-identical (contract-guard). ``native_
              metadata`` is the EXISTING pass-through ``RuntimeEvent.final``
              -> ``_RuntimeEventAdapter`` -> ``Result.native_metadata``
              already carries (no facade changes needed).
           5. failure: a node exception (``_GraphNodeFailure``, naming the
              worker's role) or an unresolvable route (``_GraphRouteMiss``,
              naming the routing node AND the state key, REQ-016) each
              become a terminal ``RuntimeEvent.error`` -- ``run()`` catches
              both and yields the error naming what went wrong; final is
              NEVER also emitted (REQ-015). A ``CancelledError`` raised by
              :meth:`cancel` propagates out of ``run()`` unchanged (no
              swallow, no substitute event) -- the caller's own cancellation
              request, honoured honestly.

Design decision #2 (``_GraphAgentRuntime`` is a DIRECT ``AgentRuntime``
implementation, not a proxy over one ``ThinRuntime`` like
``_ModeHintRuntimeProxy``): a graph run drives N per-node runtimes plus
orchestration, which a single-loop proxy cannot express. Only
``validate_agent_config``/``resolve_agent_model`` delegate to the real
factory (``_GraphRuntimeFactory``, unified model resolution, same as every
other harness path) -- ``create()`` does NOT delegate (design boundary).

Import-light (NFR-001): this module's own top-level surface is stdlib +
``harness.spec`` + ``harness.agent_assembly`` + ``harness.graph_compile``
(itself import-light) only. ``WorkflowGraph``/``ThinRuntime``/
``collect_runtime_output``/``Message`` are imported lazily, inside
``graph_compile``'s own callees, re-resolved on every call (not cached) so
tests patching ``ThinRuntime`` at its own module still take effect --
mirrors ``_ModeHintRuntimeFactory._delegate``'s documented idiom.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from swarmline.harness.agent_assembly import _DEFAULT_SYSTEM_PROMPT
from swarmline.harness.graph_compile import (
    _GraphNodeFailure,
    _GraphRouteMiss,
    compile_graph,
)
from swarmline.harness.spec import HarnessSpec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from swarmline.agent import Agent
    from swarmline.runtime.types import Message, RuntimeEvent

State = dict[str, Any]

# Queue+sentinel pattern (design-risk #1): a unique object -- never a value
# a node could plausibly enqueue -- signals "the graph task is done" to
# run()'s drain loop, queued from _drive()'s own `finally` so it fires on
# every exit path (success, node failure, route-miss, or cancellation).
_SENTINEL = object()


def build_graph_agent(spec: HarnessSpec, composition_factory: Any) -> Agent:
    """Apply a validated ``mode="graph"`` composition: return an ``Agent``
    whose ``query()``/``stream()`` executes the declared topology.

    *composition_factory* is the resolved "graph" registry factory -- the
    ``WorkflowGraph`` class itself, uninvoked (see
    ``orchestration/graph_harness_composition.py``); a fresh instance is
    constructed lazily, once per ``query()``/``stream()`` call, inside
    :meth:`_GraphAgentRuntime.run` -- never here, keeping ``build()`` itself
    free of any orchestration-substrate import (NFR-001).

    Callers (``builder.py``) MUST call
    ``graph_validation.validate_graph_topology(spec.composition)`` before
    this -- topology correctness (unknown refs, cycles, tools-declared,
    routes, ...) is entirely the validator's job; this function trusts a
    pre-validated ``CompositionSpec`` and never re-checks it.
    """
    from swarmline.agent import Agent, AgentConfig

    composition = spec.composition
    assert composition is not None  # builder.py only calls this for mode=="graph"

    config = AgentConfig(
        system_prompt=_DEFAULT_SYSTEM_PROMPT,
        runtime="thin",
        native_config={"harness_kernel": spec.kernel},
    )
    return Agent(
        config,
        runtime_factory=_GraphRuntimeFactory(spec, composition_factory),
    )


class _GraphRuntimeFactory:
    """``RuntimeFactoryPort`` for graph mode.

    ``validate_agent_config``/``resolve_agent_model``/``get_capabilities``/
    ``validate_capabilities`` delegate to the REAL factory, re-resolved on
    every call (not cached) -- same idiom as
    ``agent_assembly._ModeHintRuntimeFactory`` so model resolution stays
    unified across every harness path (design decision #2 rationale).
    ``create()`` does NOT delegate: it returns a fresh
    :class:`_GraphAgentRuntime` that owns the whole compiled-graph run,
    threading the resolved ``RuntimeConfig`` through as every per-node
    ``ThinRuntime``'s config template.
    """

    def __init__(self, spec: HarnessSpec, composition_factory: Any) -> None:
        self._spec = spec
        self._composition_factory = composition_factory

    def validate_agent_config(self, config: Any) -> None:
        self._delegate().validate_agent_config(config)

    def resolve_agent_model(self, config: Any) -> str:
        return self._delegate().resolve_agent_model(config)

    def get_capabilities(
        self, config: Any = None, runtime_override: str | None = None
    ) -> Any:
        return self._delegate().get_capabilities(
            config=config, runtime_override=runtime_override
        )

    def validate_capabilities(
        self,
        config: Any = None,
        runtime_override: str | None = None,
        required_capabilities: Any = None,
    ) -> Any:
        return self._delegate().validate_capabilities(
            config=config,
            runtime_override=runtime_override,
            required_capabilities=required_capabilities,
        )

    def create(
        self, config: Any = None, runtime_override: str | None = None, **kwargs: Any
    ) -> Any:
        return _GraphAgentRuntime(self._spec, self._composition_factory, config)

    @staticmethod
    def _delegate() -> Any:
        from swarmline.agent.runtime_factory_port import build_runtime_factory

        return build_runtime_factory()


class _GraphAgentRuntime:
    """Direct ``AgentRuntime`` implementation driving one compiled-graph run
    per ``Agent.query()``/``stream()`` call (design decision #2 -- NOT a
    proxy over a single ``ThinRuntime``)."""

    def __init__(
        self,
        spec: HarnessSpec,
        composition_factory: Any,
        node_config: Any = None,
    ) -> None:
        self._spec = spec
        self._composition_factory = composition_factory
        self._node_config = node_config
        self._task: asyncio.Task[Any] | None = None

    def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: Any,
        config: Any = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Compile the declared topology and execute it end to end.

        Seeds ``state = {"input": <last user message>, "outputs": {}}``,
        compiles a fresh ``WorkflowGraph`` from ``self._spec.composition``,
        runs ``graph.execute(state, node_interceptor=...)`` as an
        ``asyncio.Task`` (so :meth:`cancel` has something to cancel) while
        streaming a ``status`` progress event per node started/finished
        (REQ-008, Task 5 -- see module docstring step 3), then yields
        exactly ONE terminal event: ``final`` on success (REQ-006/007) or
        ``error`` naming the failed node (REQ-015) or the unresolvable
        route + key (REQ-016) -- never both, and never final alongside an
        error.
        """
        return self._run(messages, system_prompt)

    async def _run(
        self, messages: list[Message], system_prompt: str
    ) -> AsyncIterator[RuntimeEvent]:
        from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent

        state: State = {"input": _last_user_text(messages), "outputs": {}}
        graph, node_runners = self._compile(system_prompt)

        queue: asyncio.Queue[Any] = asyncio.Queue()

        async def _node_interceptor(node_id: str, node_state: State) -> State:
            """The substrate's ``NodeInterceptor`` hook (``WorkflowGraph.
            _execute_node`` delegates the ENTIRE node execution to this
            once supplied): emit "started", run the real per-node closure
            this module itself registered via ``compile_graph``, emit
            "finished", return its result unchanged -- the graph's own
            control flow (including concurrent parallel-group members,
            each calling this once) is untouched."""
            queue.put_nowait(("started", node_id))
            result = await node_runners[node_id](node_state)
            queue.put_nowait(("finished", node_id))
            return result

        async def _drive() -> State:
            try:
                return await graph.execute(state, node_interceptor=_node_interceptor)
            finally:
                # Queued on every exit path (success, node failure,
                # route-miss, cancellation) so run()'s queue-drain loop
                # below can never hang waiting for one more item.
                queue.put_nowait(_SENTINEL)

        self._task = asyncio.ensure_future(_drive())
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                phase, role = item
                yield RuntimeEvent(
                    type="status",
                    data={"role": role, "phase": phase, "text": f"{role}: {phase}"},
                )

            try:
                final_state = await self._task
            except _GraphNodeFailure as exc:
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message=str(exc),
                        details={"node": exc.role},
                    )
                )
                return
            except _GraphRouteMiss as exc:
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message=str(exc),
                        details={"node": exc.node, "key": exc.key},
                    )
                )
                return
        finally:
            # r1 fix: if the CONSUMER stops iterating early (break /
            # implicit aclose() -> GeneratorExit thrown in at the `yield`
            # above), the old code only cleared self._task without
            # touching the graph task itself -- it kept running
            # unobserved in the background (node runners' side effects
            # included) with cancel() already having lost its handle.
            # Cancel + await it here on EVERY exit path: on the happy
            # path the task is already done (cancel() is then a no-op and
            # await just re-observes the same result); on node-failure/
            # route-miss the exception was already handled above (the
            # re-raise on await is expected and swallowed); on an
            # in-flight GeneratorExit this is what actually stops the
            # background node runner. This suppression is scoped to THIS
            # re-observation only -- an external CancelledError already
            # propagating out of the `await self._task` above (the
            # runtime.cancel() path) is untouched by it and keeps
            # propagating after this finally completes.
            task, self._task = self._task, None
            if task is not None:
                if not task.done():
                    task.cancel()
                try:
                    await task
                except (Exception, asyncio.CancelledError):
                    pass

        yield RuntimeEvent.final(
            text=final_state.get("last_output", ""),
            native_metadata={"graph_state": final_state},
        )

    def _compile(self, system_prompt: str) -> tuple[Any, dict[str, Any]]:
        """Compile ``self._spec.composition`` onto a fresh ``WorkflowGraph``
        via ``graph_compile.compile_graph`` (edges, parallel groups, and
        routes alike). Returns ``(graph, node_runners)`` -- see
        :func:`~swarmline.harness.graph_compile.compile_graph`."""
        composition = self._spec.composition
        assert composition is not None
        return compile_graph(
            composition, system_prompt, self._node_config, self._composition_factory
        )

    def cancel(self) -> None:
        """Cancel the in-flight graph-execution task, if one is running.

        Cancels whatever ``asyncio.Task`` is currently awaiting
        ``graph.execute(...)`` (i.e. ``_drive()``). The queue+sentinel
        pattern in ``_run`` guarantees this can never hang the ``run()``
        generator: ``_drive()``'s own ``finally`` always queues the
        sentinel, even when unwound by ``CancelledError``, so the drain
        loop still terminates and ``run()`` re-raises the cancellation
        (never a substitute event, never a partial ``final``) instead of
        blocking forever.
        """
        if self._task is not None:
            self._task.cancel()

    async def cleanup(self) -> None:
        """No held resources to release -- each per-node ``ThinRuntime`` is
        short-lived and scoped to its own node-runner call."""
        return None

    async def __aenter__(self) -> _GraphAgentRuntime:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _last_user_text(messages: list[Message]) -> str:
    """The prompt to seed ``state["input"]`` with: the last ``role="user"``
    message, or the last message of any role if none is tagged "user"."""
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return messages[-1].content if messages else ""
