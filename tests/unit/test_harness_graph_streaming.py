"""Unit: per-node progress streaming for graph-composed agents (REQ-008).

graph-composition spec, Task 5. ``_GraphAgentRuntime.run()`` used to yield
exactly ONE event per call -- silent until the whole graph finished. Locks
the fix: ``run()`` streams a ``status`` event (``data={"role", "phase":
"started"|"finished", "text"}``) per node enter/leave, via the substrate's
OWN ``WorkflowGraph.execute(..., node_interceptor=...)`` hook (reuse-only)
-- queue+sentinel (design.md risk #1): ``_drive()`` puts one queue item
per node-phase + a sentinel in its own ``finally``, ``run()`` drains it
live, never batched post-hoc. r1 review fix: ``run()``'s outer ``finally``
also cancels + awaits the graph task -- if the CONSUMER abandons the
stream early (``break`` -> ``GeneratorExit`` at the suspended ``yield``),
the task no longer keeps running unobserved with ``cancel()`` having lost
its handle.

Fakes/helpers live in ``tests/unit/_graph_streaming_fakes.py`` (extracted
for the 400-line cap, ``_fake_redis.py`` convention). Most classes drive
``_GraphAgentRuntime.run()`` DIRECTLY (``agent/*`` off-limits here) to
assert the raw ``RuntimeEvent.data``. One class -- the liveness proof
REQ-008 names explicitly -- goes through the full ``agent.stream()`` path.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from _graph_streaming_fakes import (
    THIN_RUNTIME_PATH,
    _abc_workers,
    _collect,
    _direct_runtime,
    _fake_thin_runtime_cls,
    _progress,
    _rw_workers,
)

from swarmline.harness.builder import HarnessBuilder
from swarmline.harness.registries import get_composition_registry
from swarmline.harness.spec import (
    CompositionSpec,
    ParallelSpec,
    RouteSpec,
    WorkerSpec,
)
from swarmline.orchestration.graph_harness_composition import (
    register_graph_composition,
)
from swarmline.runtime.types import Message


@pytest.fixture
def clean_composition_registry(monkeypatch: pytest.MonkeyPatch):
    """Throwaway registry copy (mirrors ``test_harness_graph_apply.py``)."""
    registry = get_composition_registry()
    monkeypatch.setattr(registry, "_resolvers", dict(registry._resolvers))
    return registry


class TestGraphStreamingChainOrderAndFinalContract:
    """REQ-008 + contract-guard: chain r->w streams started/finished per
    node then one ``final`` last, byte-identical to REQ-006/007's shape."""

    async def test_chain_streams_progress_then_byte_identical_final(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls({"react": "researcher-out", "adapt": "writer-out"}),
        )
        composition = CompositionSpec(mode="graph", workers=_rw_workers())
        events = await _collect(_direct_runtime(composition))

        assert _progress(events) == [
            ("researcher", "started"),
            ("researcher", "finished"),
            ("writer", "started"),
            ("writer", "finished"),
        ]
        final_events = [e for e in events if e.type == "final"]
        assert len(final_events) == 1
        final = final_events[0]
        assert final is events[-1]
        assert set(final.data.keys()) == {
            "text",
            "new_messages",
            "metrics",
            "native_metadata",
        }
        assert final.data["text"] == "writer-out"
        assert final.data["native_metadata"]["graph_state"] == {
            "input": "swarmline",
            "outputs": {"researcher": "researcher-out", "writer": "writer-out"},
            "last_output": "writer-out",
            "last_role": "writer",
        }


class TestGraphStreamingParallelGroup:
    """REQ-008: started/finished for every parallel member (order between
    members not pinned), strictly before the join node's, then final."""

    async def test_parallel_group_streams_every_member_then_the_join_node(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
        composition = CompositionSpec(
            mode="graph",
            workers=(
                WorkerSpec(role="r1", kernel="react"),
                WorkerSpec(role="r2", kernel="adapt"),
                WorkerSpec(role="r3", kernel="reflection"),
                WorkerSpec(role="synth", kernel="planner"),
            ),
            parallel=(ParallelSpec(members=("r1", "r2", "r3"), then="synth"),),
        )
        events = await _collect(_direct_runtime(composition))
        progress = _progress(events)

        for member in ("r1", "r2", "r3"):
            assert (member, "started") in progress
            assert (member, "finished") in progress
        finished_at = [progress.index((m, "finished")) for m in ("r1", "r2", "r3")]
        assert progress.index(("synth", "started")) > max(finished_at)
        assert progress[-1] == ("synth", "finished")
        assert events[-1].type == "final"
        assert events[-1].data["text"] == "synth-out"


class TestGraphStreamingCancelMidGraph:
    """REQ-008 + r1 fix: ``cancel()`` mid-graph, and a CONSUMER abandoning
    the stream early (``break`` -> ``GeneratorExit``), both stop execution
    without a hang and without a later node ever starting."""

    async def test_cancel_after_progress_starts_stops_before_later_nodes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        node_b_entered = asyncio.Event()
        release = asyncio.Event()  # deliberately never set
        seen_hints: list[str | None] = []
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls(
                {"react": "a-out", "adapt": "b-out", "reflection": "c-out"},
                block_mode_hint="adapt",
                entered=node_b_entered,
                release=release,
                on_call=seen_hints.append,
            ),
        )
        runtime = _direct_runtime(CompositionSpec(mode="graph", workers=_abc_workers()))
        events: list[Any] = []

        async def _consume() -> None:
            async for event in runtime.run(
                messages=[Message(role="user", content="swarmline")],
                system_prompt="sp",
                active_tools=[],
            ):
                events.append(event)

        task = asyncio.create_task(_consume())
        await asyncio.wait_for(node_b_entered.wait(), timeout=1.0)
        runtime.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1.0)

        assert "reflection" not in seen_hints
        assert _progress(events) == [
            ("a", "started"),
            ("a", "finished"),
            ("b", "started"),
        ]
        assert not any(e.type == "final" for e in events)

    async def test_early_break_cancels_the_blocked_node_and_stops_later_nodes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """r1 fix: ``break`` throws ``GeneratorExit`` into run()'s
        suspended ``yield`` -- the blocked node's runner must actually
        observe ``CancelledError``, and node "c" never starts."""
        node_b_entered = asyncio.Event()
        cancelled_seen = asyncio.Event()
        release = asyncio.Event()  # only the abandonment-triggered cancel unblocks it
        seen_hints: list[str | None] = []
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls(
                {"react": "a-out", "adapt": "b-out", "reflection": "c-out"},
                block_mode_hint="adapt",
                entered=node_b_entered,
                release=release,
                on_call=seen_hints.append,
                cancelled=cancelled_seen,
            ),
        )
        composition = CompositionSpec(mode="graph", workers=_abc_workers())
        stream = _direct_runtime(composition).run(
            messages=[Message(role="user", content="swarmline")],
            system_prompt="sp",
            active_tools=[],
        )

        async def _consume_one() -> None:
            async for _event in stream:
                return  # simulates a consumer `break`-ing after 1 event

        await asyncio.wait_for(_consume_one(), timeout=1.0)
        await asyncio.wait_for(node_b_entered.wait(), timeout=1.0)
        await asyncio.wait_for(stream.aclose(), timeout=1.0)

        assert cancelled_seen.is_set()
        assert "reflection" not in seen_hints


class TestGraphStreamingErrorPathsUnchanged:
    """Contract-guard: node-failure and route-miss error events keep their
    pre-Task-5 shape; ``final`` never also emitted; progress for nodes
    that DID run before the failure still streams."""

    async def test_node_failure_error_event_unchanged_and_final_never_emitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls({"react": "researcher-out"}, fail_mode_hint="adapt"),
        )
        composition = CompositionSpec(mode="graph", workers=_rw_workers())
        events = await _collect(_direct_runtime(composition))

        assert not any(e.type == "final" for e in events)
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        error = error_events[0]
        assert error is events[-1]
        assert set(error.data.keys()) == {"kind", "message", "recoverable", "details"}
        assert error.data["kind"] == "runtime_crash"
        assert error.data["details"] == {"node": "writer"}
        assert _progress(events) == [
            ("researcher", "started"),
            ("researcher", "finished"),
            ("writer", "started"),
        ]

    async def test_route_miss_error_event_unchanged_and_final_never_emitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            THIN_RUNTIME_PATH, _fake_thin_runtime_cls({"react": "maybe"})
        )
        composition = CompositionSpec(
            mode="graph",
            workers=(
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
        events = await _collect(_direct_runtime(composition))

        assert not any(e.type == "final" for e in events)
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert error_events[0].data["details"] == {
            "node": "reviewer",
            "key": "last_output",
        }
        assert _progress(events) == [("reviewer", "started"), ("reviewer", "finished")]


class TestGraphStreamingViaAgentFacade:
    """REQ-008 end to end through ``HarnessBuilder().graph(...).build()``:
    live progress via ``agent.stream()``, and ``agent.query()`` unaffected
    (``collect_stream_result`` simply ignores ``status`` events)."""

    async def test_progress_events_stream_before_slow_node_is_released(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        register_graph_composition()
        entered = asyncio.Event()
        release = asyncio.Event()
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls(
                {"react": "a-out", "adapt": "b-out"},
                block_mode_hint="adapt",
                entered=entered,
                release=release,
            ),
        )
        workers = (
            WorkerSpec(role="a", kernel="react"),
            WorkerSpec(role="b", kernel="adapt"),
        )
        agent = HarnessBuilder().graph(workers).build()
        events: list[Any] = []

        async def _consume() -> None:
            async for event in agent.stream("swarmline"):
                events.append(event)

        task = asyncio.create_task(_consume())
        await asyncio.wait_for(entered.wait(), timeout=1.0)

        # "b" still blocked in release.wait() -- yet earlier progress
        # already streamed live, not batched post-hoc.
        status_texts = [e.text for e in events if e.type == "status"]
        assert status_texts == ["a: started", "a: finished", "b: started"]
        assert not any(e.type == "done" for e in events)

        release.set()
        await asyncio.wait_for(task, timeout=1.0)

        assert events[-1].type == "done"
        assert events[-1].text == "b-out"

    async def test_query_still_returns_terminal_answer_and_graph_state(
        self, monkeypatch: pytest.MonkeyPatch, clean_composition_registry
    ) -> None:
        register_graph_composition()
        monkeypatch.setattr(
            THIN_RUNTIME_PATH,
            _fake_thin_runtime_cls({"react": "researcher-out", "adapt": "writer-out"}),
        )
        agent = HarnessBuilder().graph(_rw_workers()).build()

        result = await agent.query("swarmline")

        assert result.ok is True
        assert result.text == "writer-out"
        assert result.native_metadata["graph_state"]["last_role"] == "writer"
