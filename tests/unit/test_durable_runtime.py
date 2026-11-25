"""TDD tests for Stage C1.1 — ``DurableRuntime`` checkpoint-after-step decorator.

Uses a scripted fake ``AgentRuntime`` (implements the protocol structurally)
plus ``InMemoryCheckpointer`` (B1.2) — zero new dependencies, zero vendor
SDKs. Covers the 9 plan-mandated tests, edge-case tests (empty ``thread_id``,
mid-flight crash, missing ``new_messages``, delegation, sanctioned
Temporal-exclusion from the vendor lazy-export map), and the fix-cycle r1
regression tests for the async-mode terminal-checkpoint race (GPT-5.5 review
MAJOR): the ``final`` checkpoint must never be written before its dependent
background progress checkpoints have landed, and must never reference a
failed/unpersisted checkpoint as its ``parent_id``.

Fakes/helpers live in ``tests/unit/_durable_fakes.py`` (extracted for the
400-line file-size cap — ``_graph_streaming_fakes.py``/``_followup_fakes.py``
convention).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging

import pytest
from _durable_fakes import (
    FailsNthRunningCheckpointer,
    RaisingOnRunningCheckpointer,
    ScriptedRuntime,
    SlowRunningCheckpointer,
    drain,
    make_config,
)

from swarmline.domain_types import Message, RuntimeEvent
from swarmline.durable import DurabilityConfig, DurableRuntime
from swarmline.protocols.runtime import AgentRuntime
from swarmline.session import InMemoryCheckpointer

# ---------------------------------------------------------------------------
# Plan-mandated tests (9)
# ---------------------------------------------------------------------------


async def test_durable_runtime_is_agent_runtime() -> None:
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = DurableRuntime(fake, InMemoryCheckpointer(), make_config())
    assert isinstance(runtime, AgentRuntime)


async def test_durable_runtime_yields_inner_events_unchanged() -> None:
    events = [
        RuntimeEvent.tool_call_started("search", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("search", "c1"),
        RuntimeEvent.final("hi"),
    ]
    fake = ScriptedRuntime(list(events))
    runtime = DurableRuntime(fake, InMemoryCheckpointer(), make_config())
    seen = await drain(runtime)
    assert seen == events


async def test_exit_mode_checkpoints_only_final() -> None:
    checkpointer = InMemoryCheckpointer()
    final_messages = [Message(role="assistant", content="done")]
    events = [
        RuntimeEvent.tool_call_started("x", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("x", "c1"),
        RuntimeEvent.final("done", new_messages=final_messages),
    ]
    fake = ScriptedRuntime(events)
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="exit"))
    await drain(runtime)

    history = await checkpointer.list("t1")
    assert len(history) == 1
    cp = await checkpointer.get("t1")
    assert cp is not None
    assert cp.state["status"] == "done"
    assert cp.state["messages"] == [m.to_dict() for m in final_messages]


async def test_sync_mode_checkpoints_each_tool_then_final() -> None:
    checkpointer = InMemoryCheckpointer()
    events = [
        RuntimeEvent.tool_call_started("a", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("a", "c1"),
        RuntimeEvent.tool_call_started("b", args={}, correlation_id="c2"),
        RuntimeEvent.tool_call_finished("b", "c2"),
        RuntimeEvent.final("done"),
    ]
    fake = ScriptedRuntime(events)
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="sync"))
    await drain(runtime)

    history = await checkpointer.list("t1")
    assert len(history) == 3
    statuses = []
    for meta in history:
        cp = await checkpointer.get("t1", checkpoint_id=meta.id)
        assert cp is not None
        statuses.append(cp.state["status"])
    assert statuses == ["running", "running", "done"]
    ts_values = [m.ts for m in history]
    assert ts_values == sorted(ts_values)
    assert history[1].parent_id == history[0].id
    assert history[2].parent_id == history[1].id


async def test_async_mode_persists_after_cleanup_drain() -> None:
    checkpointer = InMemoryCheckpointer()
    events = [
        RuntimeEvent.tool_call_started("a", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("a", "c1"),
        RuntimeEvent.tool_call_started("b", args={}, correlation_id="c2"),
        RuntimeEvent.tool_call_finished("b", "c2"),
        RuntimeEvent.final("done"),
    ]
    fake = ScriptedRuntime(events)
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="async"))
    await drain(runtime)
    await runtime.cleanup()

    history = await checkpointer.list("t1")
    assert len(history) == 3
    statuses = [
        (await checkpointer.get("t1", checkpoint_id=meta.id)).state["status"]  # type: ignore[union-attr]
        for meta in history
    ]
    assert statuses.count("running") == 2
    assert statuses.count("done") == 1
    assert fake.cleanup_called


async def test_async_background_checkpoint_failure_is_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    checkpointer = RaisingOnRunningCheckpointer()
    events = [
        RuntimeEvent.tool_call_started("a", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("a", "c1"),
        RuntimeEvent.final("done"),
    ]
    fake = ScriptedRuntime(events)
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="async"))

    with caplog.at_level(logging.ERROR):
        seen = await drain(runtime)
        await runtime.cleanup()

    assert seen == events  # no exception escaped the generator
    assert any("checkpoint" in rec.message.lower() for rec in caplog.records)
    final_cp = await checkpointer.get("t1")
    assert final_cp is not None
    assert final_cp.state["status"] == "done"


async def test_checkpoint_state_messages_are_serializable_dicts() -> None:
    checkpointer = InMemoryCheckpointer()
    events = [
        RuntimeEvent.tool_call_started("a", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("a", "c1", result_summary="ok"),
        RuntimeEvent.final(
            "done", new_messages=[Message(role="assistant", content="ok")]
        ),
    ]
    fake = ScriptedRuntime(events)
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="sync"))
    await drain(runtime, messages=[Message(role="user", content="hi")])

    history = await checkpointer.list("t1")
    assert history
    for meta in history:
        cp = await checkpointer.get("t1", checkpoint_id=meta.id)
        assert cp is not None
        json.dumps(cp.state)  # must not raise -- JSON round-trip
        assert all(isinstance(m, dict) for m in cp.state["messages"])


async def test_resource_id_round_trips_to_checkpoint() -> None:
    checkpointer = InMemoryCheckpointer()
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = DurableRuntime(
        fake, checkpointer, make_config(mode="exit", resource_id="u1")
    )
    await drain(runtime)

    cp = await checkpointer.get("t1")
    assert cp is not None
    assert cp.resource_id == "u1"


async def test_checkpoint_on_tool_false_skips_step_checkpoints() -> None:
    checkpointer = InMemoryCheckpointer()
    events = [
        RuntimeEvent.tool_call_started("a", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("a", "c1"),
        RuntimeEvent.final("done"),
    ]
    fake = ScriptedRuntime(events)
    runtime = DurableRuntime(
        fake, checkpointer, make_config(mode="sync", checkpoint_on_tool=False)
    )
    await drain(runtime)

    history = await checkpointer.list("t1")
    assert len(history) == 1
    cp = await checkpointer.get("t1")
    assert cp is not None
    assert cp.state["status"] == "done"


# ---------------------------------------------------------------------------
# Edge cases (plan "Edge cases" section, C1.1) + delegation + sanctioned
# Temporal-exclusion from the vendor lazy-export map.
# ---------------------------------------------------------------------------


def test_empty_thread_id_raises_value_error() -> None:
    with pytest.raises(ValueError, match="thread_id"):
        DurableRuntime(
            ScriptedRuntime([]),
            InMemoryCheckpointer(),
            DurabilityConfig(thread_id=""),
        )


async def test_inner_raises_midflight_leaves_partial_running_checkpoint() -> None:
    checkpointer = InMemoryCheckpointer()
    events: list[RuntimeEvent | BaseException] = [
        RuntimeEvent.tool_call_started("a", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("a", "c1"),
        RuntimeError("crash before final"),
    ]
    fake = ScriptedRuntime(events)
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="sync"))

    with pytest.raises(RuntimeError, match="crash before final"):
        await drain(runtime)

    history = await checkpointer.list("t1")
    assert len(history) == 1
    cp = await checkpointer.get("t1")
    assert cp is not None
    assert cp.state["status"] == "running"


async def test_final_without_new_messages_stores_empty_messages_done() -> None:
    checkpointer = InMemoryCheckpointer()
    # Bypass the RuntimeEvent.final() factory to simulate an absent key.
    fake = ScriptedRuntime([RuntimeEvent(type="final", data={"text": "hi"})])
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="exit"))
    await drain(runtime)

    cp = await checkpointer.get("t1")
    assert cp is not None
    assert cp.state == {"messages": [], "status": "done"}


async def test_cancel_and_context_manager_delegate_to_inner() -> None:
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = DurableRuntime(fake, InMemoryCheckpointer(), make_config())

    async with runtime as ctx:
        assert ctx is runtime
    runtime.cancel()

    assert fake.aenter_called
    assert fake.aexit_called
    assert fake.cancel_called


def test_dbos_and_prefect_lazy_export_resolve_but_construction_raises_without_sdk() -> (
    None
):
    """C1.5 semantic (supersedes the C1.1-era assumption below, now that
    ``durable/dbos.py``/``durable/prefect.py`` genuinely exist): the lazy
    map resolves the CLASSES cleanly at attribute access -- neither module
    imports its vendor SDK at module level, so `import_module(...)` +
    `getattr(...)` both succeed regardless of SDK presence. `ImportError`
    only fires at CONSTRUCTION, when no engine is injected and the SDK is
    absent (see `tests/integration/test_durable_backends.py` for the
    construction-time contract in full)."""
    import swarmline.durable as durable_pkg

    dbos_cls = durable_pkg.DbosDurableRuntime
    prefect_cls = durable_pkg.PrefectDurableRuntime
    assert dbos_cls.__name__ == "DbosDurableRuntime"
    assert prefect_cls.__name__ == "PrefectDurableRuntime"

    if importlib.util.find_spec("dbos") is None:
        with pytest.raises(ImportError, match="dbos"):
            dbos_cls(ScriptedRuntime([RuntimeEvent.final("hi")]))
    if importlib.util.find_spec("prefect") is None:
        with pytest.raises(ImportError, match="prefect"):
            prefect_cls(ScriptedRuntime([RuntimeEvent.final("hi")]))


def test_temporal_is_not_in_the_lazy_vendor_map() -> None:
    """Sanctioned deviation (plan 'Scope review 2026-07-04'): Temporal
    durability is served by the native ``swarmline.runtime.temporal`` runtime
    (``runtime="temporal"``), so it is deliberately NOT part of the vendor
    lazy-export map here (which would raise ``ImportError``, not this)."""
    import swarmline.durable as durable_pkg

    with pytest.raises(AttributeError):
        durable_pkg.TemporalDurableRuntime


# ---------------------------------------------------------------------------
# Fix-cycle r1 — async-mode terminal-checkpoint race (GPT-5.5 review MAJOR)
# ---------------------------------------------------------------------------


async def test_async_final_checkpoint_is_latest_even_with_slow_background_puts() -> (
    None
):
    """A slow background progress-checkpoint write must never be overtaken by
    the (otherwise fast) terminal ``final`` write -- ``run()`` must drain
    pending background checkpoints before writing the terminal state, so the
    terminal checkpoint is always the latest, even without an explicit
    ``cleanup()`` call."""
    checkpointer = SlowRunningCheckpointer(delay=0.05)
    events = [
        RuntimeEvent.tool_call_started("a", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("a", "c1"),
        RuntimeEvent.final("done"),
    ]
    fake = ScriptedRuntime(events)
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="async"))

    await drain(runtime)  # NO cleanup() call -- run() must drain internally
    # Give any (buggy) late background write ample time to land before we
    # inspect the store -- the fix must already be durable at this point.
    await asyncio.sleep(0.15)

    history = await checkpointer.list("t1")
    assert len(history) == 2
    statuses = {
        meta.id: (await checkpointer.get("t1", checkpoint_id=meta.id)).state["status"]  # type: ignore[union-attr]
        for meta in history
    }
    assert set(statuses.values()) == {"running", "done"}
    # The store's "latest" (whatever was inserted last) must be the terminal
    # state -- a slow background progress write must never overtake it.
    latest = await checkpointer.get("t1")
    assert latest is not None
    assert latest.state["status"] == "done"


async def test_async_failed_background_put_not_referenced_as_final_parent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed progress checkpoint must never be referenced as the terminal
    checkpoint's ``parent_id`` (no dangling parent); the run still completes
    and the failure is logged, not raised."""
    checkpointer = FailsNthRunningCheckpointer(fail_at=2)
    events = [
        RuntimeEvent.tool_call_started("a", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("a", "c1"),
        RuntimeEvent.tool_call_started("b", args={}, correlation_id="c2"),
        RuntimeEvent.tool_call_finished("b", "c2"),
        RuntimeEvent.final("done"),
    ]
    fake = ScriptedRuntime(events)
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="async"))

    with caplog.at_level(logging.ERROR):
        seen = await drain(runtime)
        await runtime.cleanup()

    assert seen == events  # run still completes, error logged not raised
    assert any("checkpoint" in rec.message.lower() for rec in caplog.records)

    history = await checkpointer.list("t1")
    # Only 2 checkpoints ever persisted: the 1st progress checkpoint + final
    # (the 2nd progress checkpoint's put failed and was never persisted).
    assert len(history) == 2
    checkpoints = {
        meta.id: await checkpointer.get("t1", checkpoint_id=meta.id) for meta in history
    }
    done = next(
        cp
        for cp in checkpoints.values()
        if cp is not None and cp.state["status"] == "done"
    )
    running = next(
        cp
        for cp in checkpoints.values()
        if cp is not None and cp.state["status"] == "running"
    )
    # The terminal checkpoint's parent must be the checkpoint that actually
    # persisted -- never the failed/unpersisted 2nd progress checkpoint.
    assert done.parent_id == running.id
