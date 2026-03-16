"""DeepAgentsSubagentOrchestrator — subagent execution через DeepAgents runtime."""

from __future__ import annotations

from collections.abc import Callable

from cognitia.orchestration.runtime_helpers import collect_runtime_output
from cognitia.orchestration.subagent_types import SubagentSpec
from cognitia.orchestration.thin_subagent import ThinSubagentOrchestrator
from cognitia.runtime.deepagents import DeepAgentsRuntime
from cognitia.runtime.types import Message, RuntimeConfig


class DeepAgentsSubagentOrchestrator(ThinSubagentOrchestrator):
    """SubagentOrchestrator с реальным DeepAgents execution path.

    Lifecycle (spawn/cancel/wait/status) унаследован от ThinSubagentOrchestrator,
    но выполнение задачи идёт через DeepAgentsRuntime, а не через thin-wrapper.
    """

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
            else DeepAgentsRuntime(config=self._runtime_config, tool_executors={})
        )
        return _DeepAgentsWorkerRuntime(spec=spec, runtime=runtime)


class _DeepAgentsWorkerRuntime:
    """Адаптер subagent spec -> DeepAgentsRuntime.run()."""

    def __init__(self, *, spec: SubagentSpec, runtime: DeepAgentsRuntime) -> None:
        self._spec = spec
        self._runtime = runtime

    async def run(self, task: str) -> str:
        """Выполнить задачу через DeepAgentsRuntime и вернуть финальный текст."""
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
