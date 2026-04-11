"""Regression tests for P2 concurrency bugs.

Bug 1: WorkflowGraph.resume() globally disables interrupt for concurrent executions.
Bug 2: SessionManager._run_awaitable_sync() blocks the event loop.
Bug 3: Scheduler ignores max_concurrent_tasks from DaemonConfig.
"""

from __future__ import annotations

import asyncio

import pytest

from swarmline.daemon.scheduler import Scheduler
from swarmline.orchestration.workflow_graph import WorkflowGraph, WorkflowInterrupt
from swarmline.session.backends import InMemorySessionBackend
from swarmline.session.manager import InMemorySessionManager
from swarmline.session.types import SessionKey, SessionState


# ---------------------------------------------------------------------------
# Bug 1: WorkflowGraph.resume() concurrent isolation
# ---------------------------------------------------------------------------


class TestConcurrentResumeDoesNotRemoveSharedInterrupt:
    """Two concurrent execute/resume calls on the SAME graph instance
    must not interfere with each other's interrupt points."""

    async def test_concurrent_resume_does_not_remove_shared_interrupt(self) -> None:
        """While one execution resumes past an interrupt node, a second
        concurrent execution hitting the same node must still be interrupted."""

        async def tag_node(tag: str):
            async def _fn(state: dict) -> dict:
                state.setdefault("order", []).append(tag)
                return state

            return _fn

        async def slow_finalize(state: dict) -> dict:
            """Slow node -- gives time for the second execution to start."""
            await asyncio.sleep(0.1)
            state.setdefault("order", []).append("FINALIZE")
            return state

        wf = WorkflowGraph("concurrent-interrupt-test")
        wf.add_node("prepare", await tag_node("PREPARE"))
        wf.add_node("review", await tag_node("REVIEW"))
        wf.add_node("finalize", slow_finalize)
        wf.add_edge("prepare", "review")
        wf.add_edge("review", "finalize")
        wf.set_entry("prepare")
        wf.add_interrupt("review")

        # First execution: hits interrupt at "review"
        with pytest.raises(WorkflowInterrupt) as exc_info:
            await wf.execute({})
        interrupt1 = exc_info.value

        # Start resume of first execution (will pass through "finalize" slowly)
        resume_task = asyncio.create_task(
            wf.resume(interrupt1, human_input={"approved": True})
        )

        # Give resume a moment to start (it should skip the interrupt for itself)
        await asyncio.sleep(0.01)

        # Second execution on the SAME graph: should STILL hit the interrupt
        with pytest.raises(WorkflowInterrupt) as exc_info2:
            await wf.execute({})

        assert exc_info2.value.node_id == "review"

        # Clean up the resume task
        result1 = await resume_task
        assert "FINALIZE" in result1.get("order", [])

    async def test_resume_does_not_mutate_interrupts_set(self) -> None:
        """After resume() completes, the interrupt set must be identical
        to before the call (no global mutation)."""

        async def identity(state: dict) -> dict:
            return state

        wf = WorkflowGraph("interrupt-mutation-test")
        wf.add_node("a", identity)
        wf.add_node("b", identity)
        wf.add_node("c", identity)
        wf.add_edge("a", "b")
        wf.add_edge("b", "c")
        wf.set_entry("a")
        wf.add_interrupt("b")

        interrupts_before = frozenset(wf._interrupts)

        with pytest.raises(WorkflowInterrupt) as exc_info:
            await wf.execute({})

        await wf.resume(exc_info.value, human_input={"ok": True})

        interrupts_after = frozenset(wf._interrupts)
        assert interrupts_before == interrupts_after


# ---------------------------------------------------------------------------
# Bug 2: SessionManager blocks event loop
# ---------------------------------------------------------------------------


class TestSessionManagerDoesNotBlockLoop:
    """Verify that sync methods that call backend don't block the event loop
    when called from an async context."""

    async def test_async_get_does_not_use_sync_bridge(self) -> None:
        """SessionManager should provide async get that awaits backend
        directly instead of spawning a thread."""
        backend = InMemorySessionBackend()
        mgr = InMemorySessionManager(backend=backend)

        state = SessionState(
            key=SessionKey("u1", "t1"),
            role_id="coach",
        )
        mgr.register(state)

        # The async variant should work without blocking
        result = await mgr.aget(SessionKey("u1", "t1"))
        assert result is not None
        assert result.role_id == "coach"

    async def test_async_register_does_not_use_sync_bridge(self) -> None:
        """aregister() should await backend.save() directly."""
        backend = InMemorySessionBackend()
        mgr = InMemorySessionManager(backend=backend)

        state = SessionState(
            key=SessionKey("u1", "t1"),
            role_id="coach",
        )
        await mgr.aregister(state)

        # Verify persisted to backend
        payload = await backend.load(str(SessionKey("u1", "t1")))
        assert payload is not None
        assert payload["role_id"] == "coach"

    async def test_async_update_role_does_not_use_sync_bridge(self) -> None:
        """aupdate_role() should await backend directly."""
        backend = InMemorySessionBackend()
        mgr = InMemorySessionManager(backend=backend)

        state = SessionState(
            key=SessionKey("u1", "t1"),
            role_id="coach",
        )
        await mgr.aregister(state)

        result = await mgr.aupdate_role(
            SessionKey("u1", "t1"), "diagnostician", ["iss"]
        )
        assert result is True

        payload = await backend.load(str(SessionKey("u1", "t1")))
        assert payload is not None
        assert payload["role_id"] == "diagnostician"


# ---------------------------------------------------------------------------
# Bug 3: Scheduler ignores max_concurrent_tasks
# ---------------------------------------------------------------------------


class TestSchedulerRespectsMaxConcurrent:
    """Scheduler must honor max_concurrent to bound parallel task execution."""

    async def test_scheduler_respects_max_concurrent(self) -> None:
        """With max_concurrent=2, at most 2 tasks should run concurrently."""
        peak_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def slow_task() -> None:
            nonlocal peak_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > peak_concurrent:
                    peak_concurrent = current_concurrent
            await asyncio.sleep(0.15)
            async with lock:
                current_concurrent -= 1

        sched = Scheduler(tick_interval=0.02, max_concurrent=2)
        # Register 5 tasks that all fire immediately
        for i in range(5):
            sched.every(0.01, slow_task, name=f"task-{i}")

        stop = asyncio.Event()
        asyncio.get_event_loop().call_later(0.3, stop.set)
        await sched.run_until(stop)

        assert peak_concurrent <= 2, (
            f"Expected at most 2 concurrent tasks, but peak was {peak_concurrent}"
        )

    async def test_scheduler_max_concurrent_default_is_unlimited(self) -> None:
        """Default max_concurrent=0 means no semaphore constraint."""
        peak_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def slow_task() -> None:
            nonlocal peak_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > peak_concurrent:
                    peak_concurrent = current_concurrent
            await asyncio.sleep(0.1)
            async with lock:
                current_concurrent -= 1

        sched = Scheduler(tick_interval=0.02)  # default: no limit
        for i in range(5):
            sched.every(0.01, slow_task, name=f"task-{i}")

        stop = asyncio.Event()
        asyncio.get_event_loop().call_later(0.25, stop.set)
        await sched.run_until(stop)

        # With no limit, all 5 should be able to run concurrently
        assert peak_concurrent >= 3, (
            f"Expected concurrent execution without limit, peak was {peak_concurrent}"
        )

    async def test_scheduler_max_concurrent_from_constructor(self) -> None:
        """Verify max_concurrent is accepted as constructor parameter."""
        sched = Scheduler(max_concurrent=3)
        # Should not raise, and should store the value
        assert sched._semaphore is not None

    async def test_scheduler_does_not_accumulate_unbounded_pending_launches(self) -> None:
        """Pending asyncio tasks must stay bounded by max_concurrent."""
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocked_task() -> None:
            started.set()
            await release.wait()

        sched = Scheduler(tick_interval=0.01, max_concurrent=2)
        for i in range(5):
            sched.every(0.0 + 0.01, blocked_task, name=f"task-{i}")

        stop = asyncio.Event()

        async def _stop_soon() -> None:
            await started.wait()
            await asyncio.sleep(0.05)
            stop.set()
            release.set()

        stopper = asyncio.create_task(_stop_soon())
        await sched.run_until(stop)
        await stopper

        assert len(sched._pending_asyncio_tasks) == 0
