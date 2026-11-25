"""Unit: state-key routing compiles to real conditional edges (REQ-009/016).

graph-composition spec, Task 4. Task 3 shipped ``build_graph_agent`` with a
staged, fail-loud guard rejecting any declared ``RouteSpec`` (state-key
routing was not compiled yet). This module locks the real behavior:
``harness/graph_compile.py::compile_graph`` turns each ``RouteSpec`` into a
``WorkflowGraph.add_conditional_edge`` closure (design.md Decision 3) that
reads ``state[key]`` at run time, maps the value to a target (the ``"END"``
sentinel and parallel-group members included), falls back to ``default``
when declared, and raises a terminal, named error when the key is missing
or the value is unmapped with no default (REQ-016).

Fake seam: identical to ``test_harness_graph_apply.py`` -- lazily imported
``swarmline.runtime.thin.runtime.ThinRuntime`` is monkeypatched at its own
defining module, so every ``WorkflowGraph``/routing mechanics underneath
stay REAL; only the per-node LLM call is faked. Deterministic text is keyed
by ``mode_hint`` (``=worker.kernel``), so each worker in a topology is given
a distinct kernel.
"""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.registries import get_composition_registry
from swarmline.harness.spec import ParallelSpec, RouteSpec, WorkerSpec
from swarmline.orchestration.graph_harness_composition import (
    register_graph_composition,
)

THIN_RUNTIME_PATH = "swarmline.runtime.thin.runtime.ThinRuntime"


@pytest.fixture
def clean_composition_registry(monkeypatch: pytest.MonkeyPatch):
    """Swap in a throwaway copy of the process-wide composition registry's
    resolver dict for the duration of the test (mirrors
    ``test_harness_graph_apply.py``'s isolation fixture)."""
    registry = get_composition_registry()
    monkeypatch.setattr(registry, "_resolvers", dict(registry._resolvers))
    return registry


def _fake_thin_runtime_cls(
    outputs: dict[str, str],
    calls: list[dict[str, Any]],
) -> type:
    """Build a fresh ``ThinRuntime``-shaped fake class bound to *this test's*
    own ``outputs``/``calls`` -- deterministic text keyed by ``mode_hint``."""

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
                from swarmline.runtime.types import RuntimeEvent

                yield RuntimeEvent.final(text=outputs[mode_hint])

            return _events()

        async def cleanup(self) -> None:
            pass

    return _FakeThinRuntime


class TestGraphRouteBranchesByStateKeyValue:
    """REQ-009: a declared route reads ``state[key]`` after *source* runs and
    branches to exactly ONE of its mapped targets -- the other branch never
    executes, and ``graph_state.outputs`` only ever carries the branch that
    actually ran."""

    @pytest.mark.parametrize(
        ("decision", "expected_answer", "expected_role"),
        [
            ("approve", "publisher-out", "publisher"),
            ("reject", "archiver-out", "archiver"),
        ],
    )
    async def test_route_branches_to_mapped_target_and_answer_is_that_branch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_composition_registry,
        decision: str,
        expected_answer: str,
        expected_role: str,
    ) -> None:
        register_graph_composition()
        calls: list[dict[str, Any]] = []
        outputs = {
            "react": decision,
            "adapt": "publisher-out",
            "reflection": "archiver-out",
        }
        monkeypatch.setattr(THIN_RUNTIME_PATH, _fake_thin_runtime_cls(outputs, calls))

        agent = (
            HarnessBuilder()
            .graph(
                (
                    WorkerSpec(role="reviewer", kernel="react"),
                    WorkerSpec(role="publisher", kernel="adapt"),
                    WorkerSpec(role="archiver", kernel="reflection"),
                ),
                routes=(
                    RouteSpec(
                        source="reviewer",
                        key="last_output",
                        mapping=(("approve", "publisher"), ("reject", "archiver")),
                    ),
                ),
            )
            .build()
        )

        result = await agent.query("swarmline")

        assert result.ok is True
        assert result.text == expected_answer
        assert result.native_metadata["graph_state"]["last_role"] == expected_role
        assert result.native_metadata["graph_state"]["outputs"] == {
            "reviewer": decision,
            expected_role: expected_answer,
        }


class TestGraphRouteDefaultTarget:
    """REQ-009: an unmapped state value falls back to the declared
    ``default`` target."""

    async def test_route_falls_back_to_default_when_value_is_not_mapped(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        register_graph_composition()
        calls: list[dict[str, Any]] = []
        outputs = {"react": "unrecognized", "adapt": "fallback-out"}
        monkeypatch.setattr(THIN_RUNTIME_PATH, _fake_thin_runtime_cls(outputs, calls))

        agent = (
            HarnessBuilder()
            .graph(
                (
                    WorkerSpec(role="reviewer", kernel="react"),
                    WorkerSpec(role="fallback", kernel="adapt"),
                ),
                routes=(
                    RouteSpec(
                        source="reviewer",
                        key="last_output",
                        mapping=(("approve", "fallback"),),
                        default="fallback",
                    ),
                ),
            )
            .build()
        )

        result = await agent.query("swarmline")

        assert result.ok is True
        assert result.text == "fallback-out"
        assert result.native_metadata["graph_state"]["last_role"] == "fallback"


class TestGraphRouteToEnd:
    """REQ-009: a mapped ``"END"`` target ends the run right after *source*
    -- the answer is the routing node's OWN output (REQ-006 "the terminal
    node that actually executed")."""

    async def test_route_to_end_terminates_run_with_source_output_as_answer(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        register_graph_composition()
        calls: list[dict[str, Any]] = []
        outputs = {"react": "stop", "adapt": "never-reached"}
        monkeypatch.setattr(THIN_RUNTIME_PATH, _fake_thin_runtime_cls(outputs, calls))

        agent = (
            HarnessBuilder()
            .graph(
                (
                    WorkerSpec(role="reviewer", kernel="react"),
                    WorkerSpec(role="publisher", kernel="adapt"),
                ),
                routes=(
                    RouteSpec(
                        source="reviewer",
                        key="last_output",
                        mapping=(("stop", "END"), ("go", "publisher")),
                    ),
                ),
            )
            .build()
        )

        result = await agent.query("swarmline")

        assert result.ok is True
        assert result.text == "stop"
        assert result.native_metadata["graph_state"]["last_role"] == "reviewer"
        assert result.native_metadata["graph_state"]["outputs"] == {"reviewer": "stop"}
        assert [c["mode_hint"] for c in calls] == ["react"]


class TestGraphRouteTargetIsParallelGroupMember:
    """REQ-009: a route target that names a parallel-group member enters the
    GROUP as a whole (substrate-id rewrite, same as a regular edge)."""

    async def test_route_target_member_of_parallel_group_enters_whole_group(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        register_graph_composition()
        calls: list[dict[str, Any]] = []
        outputs = {
            "react": "go",
            "adapt": "r1-out",
            "reflection": "r2-out",
            "planner": "synth-out",
        }
        monkeypatch.setattr(THIN_RUNTIME_PATH, _fake_thin_runtime_cls(outputs, calls))

        agent = (
            HarnessBuilder()
            .graph(
                (
                    WorkerSpec(role="reviewer", kernel="react"),
                    WorkerSpec(role="r1", kernel="adapt"),
                    WorkerSpec(role="r2", kernel="reflection"),
                    WorkerSpec(role="synth", kernel="planner"),
                ),
                parallel=(ParallelSpec(members=("r1", "r2"), then="synth"),),
                routes=(
                    RouteSpec(
                        source="reviewer",
                        key="last_output",
                        mapping=(("go", "r1"),),
                    ),
                ),
            )
            .build()
        )

        result = await agent.query("swarmline")

        assert result.ok is True
        assert result.text == "synth-out"
        assert result.native_metadata["graph_state"]["outputs"] == {
            "reviewer": "go",
            "r1": "r1-out",
            "r2": "r2-out",
            "synth": "synth-out",
        }


class TestGraphRouteMissIsTerminalAndNamed:
    """REQ-016: a route that cannot resolve a target at run time -- the key
    is absent from state, or its value is unmapped with no default -- ends
    the run with a terminal error event naming BOTH the routing node and the
    key; ``final`` is never also emitted, and no partial answer is given."""

    async def test_route_miss_when_key_absent_from_state_yields_named_error(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        register_graph_composition()
        calls: list[dict[str, Any]] = []
        outputs = {"react": "approve"}
        monkeypatch.setattr(THIN_RUNTIME_PATH, _fake_thin_runtime_cls(outputs, calls))

        agent = (
            HarnessBuilder()
            .graph(
                (
                    WorkerSpec(role="reviewer", kernel="react"),
                    WorkerSpec(role="publisher", kernel="adapt"),
                ),
                routes=(
                    RouteSpec(
                        source="reviewer",
                        key="nonexistent",
                        mapping=(("approve", "publisher"),),
                    ),
                ),
            )
            .build()
        )

        result = await agent.query("swarmline")

        assert result.ok is False
        assert result.text == ""
        assert result.error is not None
        assert "reviewer" in result.error
        assert "nonexistent" in result.error

    async def test_route_miss_when_value_unmapped_and_no_default_yields_named_error(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        register_graph_composition()
        calls: list[dict[str, Any]] = []
        outputs = {"react": "maybe"}
        monkeypatch.setattr(THIN_RUNTIME_PATH, _fake_thin_runtime_cls(outputs, calls))

        agent = (
            HarnessBuilder()
            .graph(
                (
                    WorkerSpec(role="reviewer", kernel="react"),
                    WorkerSpec(role="publisher", kernel="adapt"),
                ),
                routes=(
                    RouteSpec(
                        source="reviewer",
                        key="last_output",
                        mapping=(("approve", "publisher"),),
                    ),
                ),
            )
            .build()
        )

        result = await agent.query("swarmline")

        assert result.ok is False
        assert result.text == ""
        assert result.error is not None
        assert "reviewer" in result.error
        assert "last_output" in result.error


class TestGraphRouteKeyValueIsUnhashable:
    """GPT-5.5 review r2 (Task 4): ``state["outputs"]`` is itself a dict --
    a route keyed on such a field must not raise a raw ``TypeError`` from
    ``value in mapping``. Unhashable is simply unmapped: falls back to
    ``default`` when declared, else route-miss (REQ-016)."""

    @pytest.mark.parametrize(
        ("default", "expected_ok", "expected_text"),
        [("fallback", True, "fallback-out"), (None, False, "")],
    )
    async def test_unhashable_state_value_falls_back_to_default_or_route_misses(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_composition_registry,
        default: str | None,
        expected_ok: bool,
        expected_text: str,
    ) -> None:
        register_graph_composition()
        calls: list[dict[str, Any]] = []
        outputs = {"react": "reviewer-out", "adapt": "fallback-out"}
        monkeypatch.setattr(THIN_RUNTIME_PATH, _fake_thin_runtime_cls(outputs, calls))
        agent = (
            HarnessBuilder()
            .graph(
                (
                    WorkerSpec(role="reviewer", kernel="react"),
                    WorkerSpec(role="fallback", kernel="adapt"),
                ),
                routes=(
                    RouteSpec(
                        source="reviewer",
                        key="outputs",
                        mapping=(("approve", "fallback"),),
                        default=default,
                    ),
                ),
            )
            .build()
        )

        result = await agent.query("swarmline")

        assert result.ok is expected_ok
        assert result.text == expected_text
        if not expected_ok:
            assert result.error is not None
            assert "reviewer" in result.error and "outputs" in result.error
