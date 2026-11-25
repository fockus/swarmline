"""Tests for the `orchestrate` tool + recursion depth-guard (Epic G, Task 8A).

TDD for REQ-019 (an `orchestrate` tool an agent can call to launch a bounded
sub-orchestration) + REQ-020 half (numeric recursion-depth guard). Uses an
offline stub `SubEngine` (no `OrchestratorEngine`, no network) so the tool
executor's own binding/refusal logic is exercised in isolation.
"""

from __future__ import annotations

from swarmline.orchestration.autopilot.tools import create_orchestrate_tool
from swarmline.orchestration.autopilot.types import GateVerdict, OrchestrationResult


class _StubEngine:
    """Offline stand-in for `OrchestratorEngine` — records calls, no I/O."""

    def __init__(self, result: OrchestrationResult) -> None:
        self._result = result
        self.run_calls: list[str | None] = []

    async def run(
        self, goal: str | None = None, *, mode: str = "dynamic", config=None
    ) -> OrchestrationResult:
        self.run_calls.append(goal)
        return self._result


def _done_result() -> OrchestrationResult:
    return OrchestrationResult(
        status="done",
        blueprint=None,
        contract=None,
        verdict=GateVerdict(passed=True),
    )


async def test_orchestrate_tool_runs_subengine() -> None:
    engine = _StubEngine(_done_result())
    executor = create_orchestrate_tool(engine, depth=0)

    output = await executor({"goal": "build X"})

    assert engine.run_calls == ["build X"]
    assert "done" in output


async def test_orchestrate_tool_refuses_beyond_recursion_depth() -> None:
    engine = _StubEngine(_done_result())
    executor = create_orchestrate_tool(
        engine, depth=2
    )  # == default max_recursion_depth

    output = await executor({"goal": "build X"})

    assert engine.run_calls == []
    assert "refused" in output
    assert "depth" in output or "limit" in output
