"""Agent-assembly substrate for ``HarnessBuilder.build()`` — decorators + supervisor apply.

harness-composition spec, Task 2 (REQ-002, REQ-004, REQ-008, REQ-009,
REQ-012), split out of ``builder.py`` (I-076) to keep both modules under the
SRP line-count ceiling. Holds the two pieces of machinery ``build()``
delegates to once validation/registry-consultation is done:

- :class:`_ModeHintRuntimeFactory` / :class:`_ModeHintRuntimeProxy` — the
  ``RuntimeFactoryPort``/``AgentRuntime`` decorators that pin
  ``mode_hint=spec.kernel`` on every ``run()`` call, so a bare
  ``Agent(AgentConfig(runtime="thin"))`` actually resolves to
  ``spec.kernel`` instead of always falling back to "conversational".
- :class:`_SupervisorRuntimeFactory` / :class:`_SupervisorRuntimeProxy` —
  the same decorators extended to also merge the supervisor tool surface
  onto every created runtime (I-066).
- :func:`build_supervisor_agent` — the supervisor-apply construction logic:
  wires the 5 supervisor tools onto a live ``SupervisorState`` and returns
  an ``Agent`` that actually runs on that substrate.

Import-light: every ``swarmline``-internal name outside this module's own
package is imported lazily, inside method/function bodies (this module's
own module-level surface is stdlib/typing/``harness.spec`` only) — so
importing ``swarmline.harness.agent_assembly`` never eagerly pulls the
supervisor substrate; only calling :func:`build_supervisor_agent` does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from swarmline.harness.spec import HarnessSpec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from swarmline.agent import Agent

#: HarnessSpec carries no ``system_prompt`` field — ``AgentConfig`` requires
#: a non-empty one, so the builder supplies a minimal, generic default.
#: Overriding it is out of scope (not covered by REQ-002/004/008/009/012).
_DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful AI agent assembled through the swarmline harness."
)


def build_supervisor_agent(spec: HarnessSpec, composition_factory: Any) -> Agent:
    """Apply the supervisor composition (I-066): wire the 5 supervisor
    tools onto a live ``SupervisorState`` and return an ``Agent`` that
    actually runs on that substrate.

    ``composition_factory`` is ``build_supervisor`` itself (the resolver
    returns the FACTORY, uninvoked); called here with a fresh
    ``SupervisorState``/``ThinSubagentOrchestrator`` pair.

    Only ``supervisor.active_tools``/``.local_tools`` are used — the
    pre-built ``supervisor.runtime`` (build-time config only) is
    DISCARDED; the ``Agent`` facade builds a correctly, per-query
    configured runtime via its own ``runtime_factory`` extension point
    instead (``_SupervisorRuntimeFactory``, same mechanism as the
    non-composed ``_ModeHintRuntimeFactory``, extended with the tools).

    Import-light: every supervisor-substrate name is lazy, HERE only.
    """
    from datetime import datetime, timezone

    from swarmline.agent import Agent, AgentConfig
    from swarmline.orchestration.supervisor.blackboard import Blackboard
    from swarmline.orchestration.supervisor.state import SupervisorState
    from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator
    from swarmline.orchestration.types import Plan

    # ponytail: EMPTY Plan (no goal/steps seeded from the query) + a
    # default ThinSubagentOrchestrator() (no per-worker kernel/tools/
    # model/llm_call threading from CompositionSpec.workers). Deliberate
    # I-066 scope-boundary deferrals, tracked as follow-ups.
    plan = Plan(
        id="harness-supervisor",
        goal="",
        steps=[],
        created_at=datetime.now(timezone.utc),
    )
    state = SupervisorState(Blackboard(plan=plan))
    orchestrator = ThinSubagentOrchestrator()
    supervisor = composition_factory(state, orchestrator)

    config = AgentConfig(
        system_prompt=_DEFAULT_SYSTEM_PROMPT,
        runtime="thin",
        native_config={"harness_kernel": spec.kernel},
    )
    return Agent(
        config,
        runtime_factory=_SupervisorRuntimeFactory(
            spec.kernel, supervisor.local_tools, supervisor.active_tools
        ),
    )


class _ModeHintRuntimeFactory:
    """``RuntimeFactoryPort`` decorator that pins ``mode_hint`` on the built runtime.

    Forces ``spec.kernel`` onto every ``run()`` call (via
    ``_ModeHintRuntimeProxy``); everything else delegates to the real
    ``RuntimeFactoryPort``, re-resolved on every call (not cached) so tests
    patching ``RuntimeFactory`` around ``Agent.query()`` still take effect.
    """

    def __init__(self, mode_hint: str) -> None:
        self._mode_hint = mode_hint

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
        runtime = self._delegate().create(
            config=config, runtime_override=runtime_override, **kwargs
        )
        return _ModeHintRuntimeProxy(runtime, self._mode_hint)

    @staticmethod
    def _delegate() -> Any:
        from swarmline.agent.runtime_factory_port import build_runtime_factory

        return build_runtime_factory()


class _ModeHintRuntimeProxy:
    """``AgentRuntime`` decorator pinning ``mode_hint`` on every ``run()`` call.

    Delegates the full 4-method ``AgentRuntime`` protocol to the wrapped
    runtime — ``run`` defaults ``mode_hint`` to the harness kernel; an
    explicit caller-supplied ``mode_hint`` still wins.
    """

    def __init__(self, runtime: Any, mode_hint: str) -> None:
        self._runtime = runtime
        self._mode_hint = mode_hint

    def run(
        self,
        *,
        messages: Any,
        system_prompt: str,
        active_tools: Any,
        config: Any = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[Any]:
        """Delegate to the wrapped runtime, pinning ``mode_hint`` to the harness kernel."""
        return self._runtime.run(
            messages=messages,
            system_prompt=system_prompt,
            active_tools=active_tools,
            config=config,
            mode_hint=mode_hint if mode_hint is not None else self._mode_hint,
        )

    async def cleanup(self) -> None:
        await self._runtime.cleanup()

    def cancel(self) -> None:
        self._runtime.cancel()

    async def __aenter__(self) -> _ModeHintRuntimeProxy:
        await self._runtime.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._runtime.__aexit__(*exc)


class _SupervisorRuntimeFactory(_ModeHintRuntimeFactory):
    """``_ModeHintRuntimeFactory`` extended to also wire the supervisor tool
    surface onto every created runtime (I-066). Reuses everything else
    VERBATIM from the parent — only ``__init__``/``create`` differ.
    """

    def __init__(
        self, mode_hint: str, local_tools: dict[str, Any], active_tools: list[Any]
    ) -> None:
        super().__init__(mode_hint)
        self._local_tools = local_tools
        self._active_tools = active_tools

    def create(
        self, config: Any = None, runtime_override: str | None = None, **kwargs: Any
    ) -> Any:
        # User tool_executors (merged by RuntimeFactory._create_thin) override
        # supervisor tools on a name collision — same precedence it uses.
        merged = {**self._local_tools, **(kwargs.pop("local_tools", None) or {})}
        runtime = self._delegate().create(
            config=config,
            runtime_override=runtime_override,
            local_tools=merged,
            **kwargs,
        )
        return _SupervisorRuntimeProxy(runtime, self._mode_hint, self._active_tools)


class _SupervisorRuntimeProxy(_ModeHintRuntimeProxy):
    """``_ModeHintRuntimeProxy`` extended to merge the supervisor active-tools
    surface into every ``run()`` call (I-066). Reuses ``cleanup``/``cancel``/
    ``__aenter__``/``__aexit__`` VERBATIM from the parent — only ``__init__``
    and ``run`` differ.
    """

    def __init__(self, runtime: Any, mode_hint: str, active_tools: list[Any]) -> None:
        super().__init__(runtime, mode_hint)
        self._active_tools = active_tools

    def run(
        self,
        *,
        messages: Any,
        system_prompt: str,
        active_tools: Any,
        config: Any = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[Any]:
        """Pin ``mode_hint`` (parent behavior) AND merge the supervisor's
        tools into ``active_tools`` — append any supervisor ``ToolSpec``
        not already present by ``.name``, caller order first.
        """
        existing_names = {tool.name for tool in active_tools}
        merged_tools = list(active_tools) + [
            tool for tool in self._active_tools if tool.name not in existing_names
        ]
        return super().run(
            messages=messages,
            system_prompt=system_prompt,
            active_tools=merged_tools,
            config=config,
            mode_hint=mode_hint,
        )
