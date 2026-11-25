"""Unit: ``build()`` APPLIES graph composition -> live Agent (REQ-004..007/015/017).

graph-composition spec, Task 3. Before this task, a ``mode="graph"``
composition survived ``validate_graph_topology`` (Task 2) but ``build()``
still discarded the resolved factory -- ``.graph(...).build()`` returned a
kernel-only ``Agent``, never one that actually ran the declared topology.
This module locks the fix: ``harness/graph_assembly.py::build_graph_agent``
compiles the declared/default topology onto a REAL ``WorkflowGraph`` (the
existing substrate, reuse-only) and returns an ``Agent`` whose
``query()``/``stream()`` executes it end to end.

Fake seam (design.md-sanctioned "minimal seam", NOT ``WorkflowGraph``
itself): ``swarmline.runtime.thin.runtime.ThinRuntime`` is lazily imported
INSIDE the per-node runner closure on every call (mirrors
``_ModeHintRuntimeFactory._delegate``'s "re-resolved on every call, not
cached" idiom) -- so ``monkeypatch.setattr`` on the class at its OWN
defining module intercepts every per-node construction, without mocking
``WorkflowGraph``/``execute()`` at all. The fake's ``run()`` returns
deterministic text keyed by ``mode_hint`` (``=worker.kernel``) -- every
worker in a given topology is given a DISTINCT kernel so the recorded
``mode_hint`` also proves REQ-006 (kernel pinning) and lets fan-out
members be told apart without inventing a second seam.

Isolation: mirrors ``test_harness_supervisor_apply.py``'s
``clean_composition_registry`` fixture -- swaps in a throwaway copy of the
process-wide composition registry's resolver dict per test, so
``register_graph_composition()``/``register_supervisor_composition()``
calls here never leak into sibling test modules that assert composition
modes are NOT registered by default.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.registries import get_composition_registry
from swarmline.harness.spec import (
    ParallelSpec,
    RouteSpec,
    WorkerSpec,
)
from swarmline.orchestration.graph_harness_composition import (
    register_graph_composition,
)
from swarmline.orchestration.supervisor.harness_composition import (
    register_supervisor_composition,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

THIN_RUNTIME_PATH = "swarmline.runtime.thin.runtime.ThinRuntime"


@pytest.fixture
def clean_composition_registry(monkeypatch: pytest.MonkeyPatch):
    """Swap in a throwaway copy of the process-wide composition registry's
    resolver dict for the duration of the test (mirrors
    ``test_harness_supervisor_apply.py``'s isolation fixture)."""
    registry = get_composition_registry()
    monkeypatch.setattr(registry, "_resolvers", dict(registry._resolvers))
    return registry


def _fake_thin_runtime_cls(
    outputs: dict[str, str],
    calls: list[dict[str, Any]],
    *,
    fail_mode_hint: str | None = None,
) -> type:
    """Build a fresh ``ThinRuntime``-shaped fake class bound to *this test's*
    own ``outputs``/``calls`` -- deterministic text keyed by ``mode_hint``.
    ``fail_mode_hint``, if given, yields a terminal error event for that one
    node instead (surfaces as ``RuntimeError`` via ``collect_runtime_output``,
    REQ-015 fixture)."""

    class _FakeThinRuntime:
        def __init__(
            self, *, config: Any = None, llm_call: Any = None, **_: Any
        ) -> None:
            self.config = config

        def run(
            self,
            *,
            messages: Any,
            system_prompt: str,
            active_tools: Any,
            config: Any = None,
            mode_hint: str | None = None,
        ) -> Any:
            calls.append(
                {
                    "task": messages[0].content,
                    "system_prompt": system_prompt,
                    "mode_hint": mode_hint,
                }
            )

            async def _events():
                from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent

                if mode_hint == fail_mode_hint:
                    yield RuntimeEvent.error(
                        RuntimeErrorData(kind="tool_error", message="boom")
                    )
                    return
                yield RuntimeEvent.final(text=outputs[mode_hint])

            return _events()

        async def cleanup(self) -> None:
            pass

    return _FakeThinRuntime


class TestGraphAgentRunsChainEndToEnd:
    """REQ-004/005/006/007: ``.graph(...).build()`` returns an Agent whose
    ``query()`` actually executes the declared chain on a REAL
    ``WorkflowGraph`` (fake only swaps the per-node ``ThinRuntime``)."""

    async def test_chain_answers_with_writer_output_and_pins_per_worker_mode_hints(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        """REQ-004/006/007: researcher's node runner gets mode_hint="react",
        writer's gets mode_hint="adapt" (never a shared/hardcoded hint);
        writer's task is researcher's output (prompt-chaining, design.md);
        the final answer is the terminal (writer's) output; ``graph_state``
        carries the seeded input plus every node's output."""
        register_graph_composition()
        calls: list[dict[str, Any]] = []
        outputs = {"react": "researcher-out", "adapt": "writer-out"}
        monkeypatch.setattr(THIN_RUNTIME_PATH, _fake_thin_runtime_cls(outputs, calls))

        agent = (
            HarnessBuilder()
            .graph(
                (
                    WorkerSpec(role="researcher", kernel="react"),
                    WorkerSpec(role="writer", kernel="adapt"),
                )
            )
            .build()
        )

        result = await agent.query("swarmline")

        assert result.ok is True
        assert result.text == "writer-out"
        assert [c["mode_hint"] for c in calls] == ["react", "adapt"]
        assert calls[1]["task"] == "researcher-out"
        assert result.native_metadata is not None
        assert result.native_metadata["graph_state"] == {
            "input": "swarmline",
            "outputs": {"researcher": "researcher-out", "writer": "writer-out"},
            "last_output": "writer-out",
            "last_role": "writer",
        }

    async def test_single_worker_without_declared_topology_defaults_to_linear_chain_to_end(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        """REQ-005: no edges/parallel/routes declared -> linear default (a
        lone worker chains straight to END)."""
        register_graph_composition()
        calls: list[dict[str, Any]] = []
        outputs = {"react": "solo-out"}
        monkeypatch.setattr(THIN_RUNTIME_PATH, _fake_thin_runtime_cls(outputs, calls))

        agent = (
            HarnessBuilder().graph((WorkerSpec(role="solo", kernel="react"),)).build()
        )

        result = await agent.query("swarmline")

        assert result.text == "solo-out"
        assert result.native_metadata["graph_state"]["last_role"] == "solo"


class TestGraphAgentRunsFanoutEndToEnd:
    """REQ-004/007: a declared ``parallel`` group fans out to 3 members and
    joins on ``synth`` -- every member's output survives into
    ``graph_state.outputs`` (design.md's in-place-mutation contract)."""

    async def test_fanout_three_members_join_and_answer_is_synth_output(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        register_graph_composition()
        calls: list[dict[str, Any]] = []
        outputs = {
            "react": "r1-out",
            "adapt": "r2-out",
            "reflection": "r3-out",
            "planner": "synth-out",
        }
        monkeypatch.setattr(THIN_RUNTIME_PATH, _fake_thin_runtime_cls(outputs, calls))

        agent = (
            HarnessBuilder()
            .graph(
                (
                    WorkerSpec(role="r1", kernel="react"),
                    WorkerSpec(role="r2", kernel="adapt"),
                    WorkerSpec(role="r3", kernel="reflection"),
                    WorkerSpec(role="synth", kernel="planner"),
                ),
                parallel=(ParallelSpec(members=("r1", "r2", "r3"), then="synth"),),
            )
            .build()
        )

        result = await agent.query("swarmline")

        assert result.text == "synth-out"
        assert result.native_metadata["graph_state"]["outputs"] == {
            "r1": "r1-out",
            "r2": "r2-out",
            "r3": "r3-out",
            "synth": "synth-out",
        }


class TestGraphAgentNodeFailureIsHonestNeverPartial:
    """REQ-015: a node failing mid-graph ends the run with a terminal error
    naming the node -- never a partial answer."""

    async def test_node_failure_mid_chain_yields_named_error_not_partial_text(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        register_graph_composition()
        calls: list[dict[str, Any]] = []
        outputs = {"react": "researcher-out"}
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls(outputs, calls, fail_mode_hint="adapt"),
        )

        agent = (
            HarnessBuilder()
            .graph(
                (
                    WorkerSpec(role="researcher", kernel="react"),
                    WorkerSpec(role="writer", kernel="adapt"),
                )
            )
            .build()
        )

        result = await agent.query("swarmline")

        assert result.ok is False
        assert result.text == ""
        assert result.error is not None
        assert "writer" in result.error


class TestGraphAgentRoutesAreNoLongerStaged:
    """Task 4 lifts the Task 3 staging guard this class used to lock:
    declaring ``routes`` no longer raises ``GraphRoutesNotImplemented`` --
    that class is gone entirely, and a route-bearing spec builds and runs
    like any other graph. Full state-key routing behavior (branching,
    default, END, parallel-group targets, route-miss) is exercised in
    ``test_harness_graph_routing.py``; this module only locks the
    guard-removal fact, next to the Task-3 test it replaces."""

    def test_graph_assembly_no_longer_exports_graph_routes_not_implemented(
        self,
    ) -> None:
        import swarmline.harness.graph_assembly as module

        assert not hasattr(module, "GraphRoutesNotImplemented")

    async def test_declared_routes_build_and_run_through_the_full_build_path(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        register_graph_composition()
        calls: list[dict[str, Any]] = []
        outputs = {"react": "x", "adapt": "b-out"}
        monkeypatch.setattr(THIN_RUNTIME_PATH, _fake_thin_runtime_cls(outputs, calls))

        agent = (
            HarnessBuilder()
            .graph(
                (
                    WorkerSpec(role="a", kernel="react"),
                    WorkerSpec(role="b", kernel="adapt"),
                ),
                routes=(
                    RouteSpec(source="a", key="last_output", mapping=(("x", "b"),)),
                ),
            )
            .build()
        )

        result = await agent.query("swarmline")

        assert result.ok is True
        assert result.text == "b-out"


class TestGraphAgentByteIdenticalNonGraphPaths:
    """REQ-017: supervisor/``composition=None`` never invoke
    ``build_graph_agent`` -- ``build()`` keeps its pre-Task-3 behavior for
    every mode OTHER than "graph"."""

    def test_supervisor_composition_never_invokes_build_graph_agent(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        register_supervisor_composition()
        spy = MagicMock()
        monkeypatch.setattr("swarmline.harness.graph_assembly.build_graph_agent", spy)

        from swarmline.agent import Agent

        agent = (
            HarnessBuilder()
            .supervisor(workers=(WorkerSpec(role="researcher"),))
            .build()
        )

        assert isinstance(agent, Agent)
        spy.assert_not_called()

    def test_composition_none_never_invokes_build_graph_agent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = MagicMock()
        monkeypatch.setattr("swarmline.harness.graph_assembly.build_graph_agent", spy)

        from swarmline.agent import Agent

        agent = HarnessBuilder().build()

        assert isinstance(agent, Agent)
        spy.assert_not_called()


class TestGraphAssemblyModuleImportLight:
    """NFR-001: merely importing ``harness.graph_assembly`` or its Task-4
    sibling ``harness.graph_compile`` never eagerly pulls
    ``workflow_graph``/``workflow_executor``. Mirrors
    ``test_harness_graph_validation.py``'s own precedent test AND its own
    documented caveat: ``swarmline.runtime.thin.runtime`` is ALREADY present
    in ``sys.modules`` the moment the top-level ``swarmline`` package is
    imported (a pre-existing, unrelated eager import) -- so it is
    deliberately NOT asserted absent here, only the orchestration substrate
    this task's compilation path would pull is."""

    def test_importing_graph_assembly_does_not_pull_workflow_graph_substrate(
        self,
    ) -> None:
        code = (
            "import sys\n"
            "import swarmline.harness.graph_assembly\n"
            "mods = sys.modules\n"
            "assert 'swarmline.orchestration.workflow_graph' not in mods, ("
            "'importing graph_assembly eagerly pulled workflow_graph')\n"
            "assert 'swarmline.orchestration.workflow_executor' not in mods, ("
            "'importing graph_assembly eagerly pulled workflow_executor')\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout

    def test_importing_graph_compile_does_not_pull_workflow_graph_substrate(
        self,
    ) -> None:
        code = (
            "import sys\n"
            "import swarmline.harness.graph_compile\n"
            "mods = sys.modules\n"
            "assert 'swarmline.orchestration.workflow_graph' not in mods, ("
            "'importing graph_compile eagerly pulled workflow_graph')\n"
            "assert 'swarmline.orchestration.workflow_executor' not in mods, ("
            "'importing graph_compile eagerly pulled workflow_executor')\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout
