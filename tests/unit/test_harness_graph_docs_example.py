"""Unit: ``docs/harness.md``'s "Graph composition" section — executable proof.

graph-composition spec, Task 6 (NFR-005 + spec close). Mirrors
``test_harness_taskloom_example.py``'s role for the "Embedding in a
downstream app" section: every code snippet the new "## Graph composition"
section of ``docs/harness.md`` quotes (workers, kernels, edges/parallel/
routes, the explicit bootstrap call) is reproduced here verbatim and
actually run — proving the doc's claims (linear-chain default, fan-out
join, declarative routing incl. ``default -> END`` and route-miss,
``graph_state`` shape, per-node progress streaming, bootstrap honesty) are
true, not merely narrated. Written before the doc section existed (RED:
the examples below already exercise real Tasks 1-5 code paths, but nothing
in ``docs/harness.md`` documented them yet).

Fake seam: identical to ``test_harness_graph_streaming.py`` — the lazily
imported ``ThinRuntime`` is monkeypatched at its own module
(``_graph_streaming_fakes.THIN_RUNTIME_PATH``); ``WorkflowGraph`` stays
REAL. Isolation: ``clean_composition_registry`` mirrors
``test_harness_graph_apply.py``'s own fixture so registering "graph" here
never leaks into sibling modules that assert composition modes are NOT
registered by default.
"""

from __future__ import annotations

from typing import Any

import pytest
from _graph_streaming_fakes import THIN_RUNTIME_PATH, _fake_thin_runtime_cls

from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.registries import (
    CompositionBlockNotFound,
    get_composition_registry,
)
from swarmline.harness.spec import (
    CompositionSpec,
    ParallelSpec,
    RouteSpec,
    WorkerSpec,
)
from swarmline.harness.validation import validate_harness_spec
from swarmline.harness.yaml_loader import load_harness_yaml
from swarmline.orchestration.graph_harness_composition import (
    register_graph_composition,
)


@pytest.fixture
def clean_composition_registry(monkeypatch: pytest.MonkeyPatch):
    """Throwaway registry-resolver-dict copy (mirrors
    ``test_harness_graph_apply.py``/``test_harness_graph_streaming.py``)."""
    registry = get_composition_registry()
    monkeypatch.setattr(registry, "_resolvers", dict(registry._resolvers))
    return registry


def _docs_chain_workers() -> tuple[WorkerSpec, ...]:
    """docs/harness.md's "Graph composition" chain example: no edges
    declared -> linear default (REQ-005)."""
    return (
        WorkerSpec(role="researcher", kernel="react"),
        WorkerSpec(role="writer", kernel="adapt"),
    )


class TestDocsChainExampleSpecEquality:
    """ "The spec" + "YAML pipeline": the doc's fluent ``.graph(...)`` call
    and its quoted YAML file compile into the identical ``CompositionSpec``
    (single source of truth — same guarantee the pre-existing supervisor
    section already documents)."""

    def test_sdk_and_yaml_chain_examples_produce_the_identical_spec(
        self, tmp_path: Any
    ) -> None:
        sdk_spec = HarnessBuilder().graph(_docs_chain_workers()).spec

        yaml_path = tmp_path / "graph_chain.yaml"
        yaml_path.write_text(
            "kernel: react\n"
            "composition:\n"
            "  mode: graph\n"
            "  workers:\n"
            "    - role: researcher\n"
            "      kernel: react\n"
            "    - role: writer\n"
            "      kernel: adapt\n"
        )
        yaml_spec = load_harness_yaml(str(yaml_path))

        assert sdk_spec == yaml_spec
        assert sdk_spec.composition == CompositionSpec(
            mode="graph", workers=_docs_chain_workers()
        )

    def test_docs_chain_example_passes_validate_harness_spec(
        self, clean_composition_registry
    ) -> None:
        register_graph_composition()
        spec = HarnessBuilder().graph(_docs_chain_workers()).spec

        assert validate_harness_spec(spec) is None


class TestDocsBootstrapHonesty:
    """The doc's honesty claim: unlike the still-deferred ``supervisor``
    block documented above it, "graph" fails loud naming "graph" BEFORE
    ``register_graph_composition()`` runs, and returns a genuinely live,
    graph-composed ``Agent`` right after — no I-052-style backlog item
    pending, matching the doc's "no change to this doc's example code"
    framing for the equivalent supervisor case, inverted to "already true
    today for graph"."""

    def test_build_before_registration_raises_composition_block_not_found_naming_graph(
        self, clean_composition_registry
    ) -> None:
        with pytest.raises(CompositionBlockNotFound) as exc_info:
            HarnessBuilder().graph(_docs_chain_workers()).build()

        assert "graph" in str(exc_info.value)

    def test_build_after_registration_returns_a_real_agent(
        self, clean_composition_registry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.agent import Agent

        register_graph_composition()
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls({"react": "r-out", "adapt": "w-out"}),
        )

        agent = HarnessBuilder().graph(_docs_chain_workers()).build()

        assert isinstance(agent, Agent)


class TestDocsChainExampleRunsEndToEnd:
    """The doc's chain-example claim: answer = writer's output;
    ``graph_state`` carries both nodes' outputs under the documented
    shape."""

    async def test_chain_answers_with_writer_output_and_documented_graph_state(
        self, clean_composition_registry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        register_graph_composition()
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls({"react": "researcher-out", "adapt": "writer-out"}),
        )

        agent = HarnessBuilder().graph(_docs_chain_workers()).build()
        result = await agent.query("swarmline docs example")

        assert result.ok is True
        assert result.text == "writer-out"
        assert result.native_metadata["graph_state"] == {
            "input": "swarmline docs example",
            "outputs": {"researcher": "researcher-out", "writer": "writer-out"},
            "last_output": "writer-out",
            "last_role": "writer",
        }


class TestDocsFanoutExampleRunsEndToEnd:
    """The doc's fan-out example claim: 3 parallel members join on
    ``synth``; every member's output survives into ``graph_state.outputs``."""

    async def test_fanout_three_members_join_and_answer_is_synth_output(
        self, clean_composition_registry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        register_graph_composition()
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls(
                {
                    "react": "r1-out",
                    "adapt": "r2-out",
                    "reflection": "r3-out",
                    "planner": "synth-out",
                }
            ),
        )

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

        result = await agent.query("swarmline docs example")

        assert result.text == "synth-out"
        assert result.native_metadata["graph_state"]["outputs"] == {
            "r1": "r1-out",
            "r2": "r2-out",
            "r3": "r3-out",
            "synth": "synth-out",
        }


class TestDocsRouteExampleRunsEndToEnd:
    """The doc's routing example claim: ``reviewer``'s output routes to
    ``publisher`` on ``"approve"``, falls to the declared ``default``
    (``"END"``) otherwise, and a route-miss (no default, unmapped value)
    fails loud naming the routing node and the state key (REQ-016)."""

    def _route_workers(self) -> tuple[WorkerSpec, ...]:
        return (
            WorkerSpec(role="reviewer", kernel="react"),
            WorkerSpec(role="publisher", kernel="adapt"),
        )

    async def test_approve_routes_to_publisher_and_answer_is_publisher_output(
        self, clean_composition_registry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        register_graph_composition()
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls({"react": "approve", "adapt": "published"}),
        )

        agent = (
            HarnessBuilder()
            .graph(
                self._route_workers(),
                routes=(
                    RouteSpec(
                        source="reviewer",
                        key="last_output",
                        mapping=(("approve", "publisher"),),
                        default="END",
                    ),
                ),
            )
            .build()
        )

        result = await agent.query("swarmline docs example")

        assert result.ok is True
        assert result.text == "published"

    async def test_reject_falls_to_default_end_and_answer_is_reviewer_output(
        self, clean_composition_registry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        register_graph_composition()
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls({"react": "reject", "adapt": "published"}),
        )

        agent = (
            HarnessBuilder()
            .graph(
                self._route_workers(),
                routes=(
                    RouteSpec(
                        source="reviewer",
                        key="last_output",
                        mapping=(("approve", "publisher"),),
                        default="END",
                    ),
                ),
            )
            .build()
        )

        result = await agent.query("swarmline docs example")

        assert result.ok is True
        assert result.text == "reject"

    async def test_route_miss_without_default_fails_loud_naming_node_and_key(
        self, clean_composition_registry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        register_graph_composition()
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls({"react": "unmapped-verdict"}),
        )

        agent = (
            HarnessBuilder()
            .graph(
                self._route_workers(),
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

        result = await agent.query("swarmline docs example")

        assert result.ok is False
        assert result.error is not None
        assert "reviewer" in result.error
        assert "last_output" in result.error


class TestDocsPerNodeProgressStreaming:
    """The doc's per-node progress claim: ``agent.stream()`` yields a
    ``status`` event per node enter/leave, live, before the terminal
    ``done``."""

    async def test_stream_yields_started_finished_per_node_then_done(
        self, clean_composition_registry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        register_graph_composition()
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls({"react": "researcher-out", "adapt": "writer-out"}),
        )
        agent = HarnessBuilder().graph(_docs_chain_workers()).build()

        events = [event async for event in agent.stream("swarmline docs example")]

        status_texts = [e.text for e in events if e.type == "status"]
        assert status_texts == [
            "researcher: started",
            "researcher: finished",
            "writer: started",
            "writer: finished",
        ]
        assert events[-1].type == "done"
        assert events[-1].text == "writer-out"
