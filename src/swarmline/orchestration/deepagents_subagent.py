"""DeepAgentsSubagentOrchestrator - subagent execution via DeepAgents runtime."""

from __future__ import annotations

from collections.abc import Callable

from swarmline.orchestration.runtime_helpers import collect_runtime_output
from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator
from swarmline.runtime.deepagents import DeepAgentsRuntime
from swarmline.runtime.types import Message, RuntimeConfig


class DeepAgentsSubagentOrchestrator(ThinSubagentOrchestrator):
    """Deep Agents Subagent Orchestrator implementation."""

    def __init__(
        self,
        max_concurrent: int = 4,
        *,
        runtime_factory: Callable[[SubagentSpec], DeepAgentsRuntime] | None = None,
        runtime_config: RuntimeConfig | None = None,
    ) -> None:
        super().__init__(max_concurrent=max_concurrent)
        self._runtime_factory = runtime_factory
        self._runtime_config = runtime_config or RuntimeConfig(runtime_name="deepagents")

    def _create_runtime(self, spec: SubagentSpec) -> _DeepAgentsWorkerRuntime:
        runtime = (
            self._runtime_factory(spec)
            if self._runtime_factory is not None
            else DeepAgentsRuntime(
                config=self._runtime_config,
                tool_executors=dict(self._local_tools),
            )
        )
        return _DeepAgentsWorkerRuntime(
            spec=spec,
            runtime=runtime,
            tool_executors=dict(self._local_tools),
        )


class _DeepAgentsWorkerRuntime:
    """Adapter subagent spec -> DeepAgentsRuntime.run()."""

    def __init__(
        self,
        *,
        spec: SubagentSpec,
        runtime: DeepAgentsRuntime,
        tool_executors: dict[str, Callable[..., object]],
    ) -> None:
        self._spec = spec
        self._runtime = runtime
        self._tool_executors = tool_executors

    async def run(self, task: str) -> str:
        """Run."""
        missing_local_tools = [
            tool.name
            for tool in self._spec.tools
            if tool.is_local and tool.name not in self._tool_executors
        ]
        if missing_local_tools:
            missing_str = ", ".join(sorted(missing_local_tools))
            raise RuntimeError(
                f"Missing local tool executors for DeepAgents subagent: {missing_str}"
            )

        return await collect_runtime_output(
            self._runtime.run(
                messages=[Message(role="user", content=task)],
                system_prompt=self._spec.system_prompt,
                active_tools=self._spec.tools,
                config=None,
                mode_hint="subagent",
            ),
            error_prefix="DeepAgents subagent error",
        )
