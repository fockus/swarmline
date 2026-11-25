"""Unit tests for swarmline.pipeline.budget_guard — atomic check-and-debit.

Covers REQ-OSS-011: WHERE a budget guard is configured, the projected cost is
atomically checked-and-debited and the call refused if it would exceed the limit.
Works in the store's native unit (USD float, BudgetScope). The critical property
is atomicity under concurrency: a debit + the limit check happen under one lock so
two near-limit debits cannot both pass.
"""

from __future__ import annotations

import asyncio

import pytest

from swarmline.pipeline.budget_types import BudgetScope, BudgetScopeType, BudgetWindow

_LIFETIME = BudgetWindow.LIFETIME


def _scope(key: str) -> BudgetScope:
    return BudgetScope(scope_type=BudgetScopeType.AGENT, scope_id=key)


class _YieldingStore:
    """Async store double whose ops yield to the event loop.

    Models a real async-IO backend (e.g. SqlitePersistentBudgetStore uses
    asyncio.to_thread, which yields). The yield between get_usage and record_cost
    is what exposes the TOCTOU window the guard's lock must close.
    """

    def __init__(self) -> None:
        self._usage: dict[tuple[str, str], float] = {}

    async def get_usage(self, scope: BudgetScope, window: BudgetWindow) -> float:
        await asyncio.sleep(0)
        return self._usage.get((scope.scope_type.value, scope.scope_id), 0.0)

    async def record_cost(
        self, scope: BudgetScope, amount_usd: float, description: str = ""
    ) -> None:
        await asyncio.sleep(0)
        k = (scope.scope_type.value, scope.scope_id)
        self._usage[k] = self._usage.get(k, 0.0) + amount_usd


class TestBudgetGuardBasic:
    """check_and_debit permits under limit, refuses over, and records on success only."""

    async def test_permits_debit_under_limit(self) -> None:
        from swarmline.pipeline.budget_guard import BudgetGuard
        from swarmline.pipeline.budget_store import InMemoryPersistentBudgetStore

        store = InMemoryPersistentBudgetStore()
        guard = BudgetGuard(store)

        result = await guard.check_and_debit("agent-1", 0.5, limit_usd=1.0)

        assert result.allowed is True
        assert result.projected_usd == pytest.approx(0.5)
        usage = await store.get_usage(_scope("agent-1"), _LIFETIME)
        assert usage == pytest.approx(0.5)

    async def test_refuses_when_projected_exceeds_limit_and_does_not_debit(
        self,
    ) -> None:
        from swarmline.pipeline.budget_guard import BudgetGuard
        from swarmline.pipeline.budget_store import InMemoryPersistentBudgetStore

        store = InMemoryPersistentBudgetStore()
        guard = BudgetGuard(store)

        await guard.check_and_debit("agent-1", 0.8, limit_usd=1.0)
        result = await guard.check_and_debit(
            "agent-1", 0.5, limit_usd=1.0
        )  # 0.8+0.5=1.3 > 1.0

        assert result.allowed is False
        usage = await store.get_usage(_scope("agent-1"), _LIFETIME)
        assert usage == pytest.approx(0.8)  # the refused debit was NOT recorded

    async def test_exact_limit_is_allowed(self) -> None:
        from swarmline.pipeline.budget_guard import BudgetGuard
        from swarmline.pipeline.budget_store import InMemoryPersistentBudgetStore

        store = InMemoryPersistentBudgetStore()
        guard = BudgetGuard(store)

        result = await guard.check_and_debit(
            "agent-1", 1.0, limit_usd=1.0
        )  # projected == limit
        assert result.allowed is True

    async def test_isolated_keys_track_separately(self) -> None:
        from swarmline.pipeline.budget_guard import BudgetGuard
        from swarmline.pipeline.budget_store import InMemoryPersistentBudgetStore

        store = InMemoryPersistentBudgetStore()
        guard = BudgetGuard(store)

        a = await guard.check_and_debit("agent-a", 0.9, limit_usd=1.0)
        b = await guard.check_and_debit("agent-b", 0.9, limit_usd=1.0)
        assert a.allowed is True
        assert b.allowed is True


class TestBudgetGuardConcurrency:
    """Atomicity: N concurrent near-limit debits never collectively exceed the limit."""

    async def test_atomic_under_concurrency(self) -> None:
        from swarmline.pipeline.budget_guard import BudgetGuard

        store = _YieldingStore()
        guard = BudgetGuard(store)

        # limit 1.0, amount 0.25 → at most 4 debits may pass (4*0.25 == 1.0).
        results = await asyncio.gather(
            *[guard.check_and_debit("k", 0.25, limit_usd=1.0) for _ in range(10)]
        )

        allowed = [r for r in results if r.allowed]
        refused = [r for r in results if not r.allowed]
        final = await store.get_usage(_scope("k"), _LIFETIME)

        assert final <= 1.0 + 1e-9, (
            f"total debited {final} exceeded limit 1.0 — not atomic"
        )
        assert len(allowed) == 4
        assert len(refused) == 6


class TestBudgetGuardCrossInstanceAtomicity:
    """Two guards over the SAME store must share atomicity — per-instance locks are not enough.

    The race: pre-fill usage to 0.75, then fire two concurrent debits of 0.25 (one per guard).
    With per-instance locks both guards read 0.75 before either records → both compute
    projected=1.0≤1.0, both pass, total becomes 1.25 (exceeds limit).
    With a shared lock (keyed by store identity) one guard holds the lock while the other
    blocks; the second reads 1.0 and is correctly refused.
    """

    async def test_two_guards_same_store_are_atomic(self) -> None:
        from swarmline.pipeline.budget_guard import BudgetGuard

        store = _YieldingStore()
        guard_a = BudgetGuard(store)
        guard_b = BudgetGuard(store)

        # Pre-fill to 0.75: 3 sequential debits via guard_a so usage is deterministic.
        for _ in range(3):
            r = await guard_a.check_and_debit("k", 0.25, limit_usd=1.0)
            assert r.allowed  # sanity

        # Now usage=0.75, limit=1.0.  Fire one debit from each guard concurrently.
        # Only ONE should be allowed (the 4th debit hits exactly 1.0 ≤ 1.0).
        # The 5th debit (from the other guard, also reading stale 0.75) should be refused.
        results = await asyncio.gather(
            guard_a.check_and_debit("k", 0.25, limit_usd=1.0),
            guard_b.check_and_debit("k", 0.25, limit_usd=1.0),
        )

        allowed = [r for r in results if r.allowed]
        final = await store.get_usage(_scope("k"), _LIFETIME)

        assert final <= 1.0 + 1e-9, (
            f"total debited {final} exceeded limit 1.0 — cross-instance not atomic"
        )
        assert len(allowed) == 1, f"expected exactly 1 allowed, got {len(allowed)}"


class _SlottedStore:
    """Store double with __slots__ that omits __weakref__ — NOT weak-referenceable.

    This is a valid PersistentBudgetStore but cannot be used as a WeakKeyDictionary
    key (TypeError: cannot create weak reference).  BudgetGuard must work with it.
    """

    __slots__ = ("_usage",)

    def __init__(self) -> None:
        self._usage: dict[tuple[str, str], float] = {}

    async def get_usage(self, scope: BudgetScope, window: BudgetWindow) -> float:
        await asyncio.sleep(0)
        return self._usage.get((scope.scope_type.value, scope.scope_id), 0.0)

    async def record_cost(
        self, scope: BudgetScope, amount_usd: float, description: str = ""
    ) -> None:
        await asyncio.sleep(0)
        k = (scope.scope_type.value, scope.scope_id)
        self._usage[k] = self._usage.get(k, 0.0) + amount_usd


class TestBudgetGuardNonWeakRefStore:
    """BudgetGuard must accept stores that are not weak-referenceable (no __weakref__ slot).

    WeakKeyDictionary raises TypeError on such stores; dict[int, Lock] keyed by id() works
    for any object regardless of hashability or weak-referenceability.
    """

    async def test_guard_accepts_non_weakreferenceable_store(self) -> None:
        from swarmline.pipeline.budget_guard import BudgetGuard

        store = _SlottedStore()

        # Construction must not raise TypeError from WeakKeyDictionary.
        guard_a = BudgetGuard(store)
        guard_b = BudgetGuard(store)

        # Cross-instance atomicity still holds: pre-fill to 0.75, then two concurrent
        # 0.25 debits (one per guard) — exactly 1 should be allowed.
        for _ in range(3):
            r = await guard_a.check_and_debit("k", 0.25, limit_usd=1.0)
            assert r.allowed

        results = await asyncio.gather(
            guard_a.check_and_debit("k", 0.25, limit_usd=1.0),
            guard_b.check_and_debit("k", 0.25, limit_usd=1.0),
        )

        allowed = [r for r in results if r.allowed]
        final = await store.get_usage(_scope("k"), _LIFETIME)

        assert final <= 1.0 + 1e-9, (
            f"total debited {final} exceeded limit 1.0 — non-weakref store not atomic"
        )
        assert len(allowed) == 1, f"expected exactly 1 allowed, got {len(allowed)}"


class TestBudgetGuardEventLoopRebinding:
    """asyncio.Lock is loop-bound; the registry must rebind when the running loop changes.

    asyncio.Lock._get_loop() is called ONLY on the contended path (when a waiter future
    must be created).  A single free-lock acquire returns on the fast path without ever
    calling _get_loop().  Therefore the regression test must cause actual lock contention:
    two concurrent debits over the same guard — the second waiter triggers _get_loop().

    With a cached lock bound to loop 1, reused in loop 2: _get_loop() raises
    RuntimeError("bound to a different event loop").  After the fix the registry rebinds
    and creates a fresh lock for the new loop.
    """

    def test_lock_is_rebound_across_event_loops(self) -> None:
        """Two sequential asyncio.run() calls with contention over the SAME store must not raise.

        The contention (asyncio.gather of two debits) is required to exercise the
        _get_loop() code path that triggers the RuntimeError on cross-loop lock reuse.
        """
        from swarmline.pipeline.budget_guard import BudgetGuard

        store = _YieldingStore()

        async def _contended_debits():
            g = BudgetGuard(store)
            # Two concurrent debits on the SAME guard: the second one blocks waiting
            # for the lock and calls _get_loop() to create a waiter future.
            # Loop 1: _get_loop() binds lock._loop = loop_1.
            # Loop 2 (before fix): _get_loop() finds loop_2 != loop_1 → RuntimeError.
            await asyncio.gather(
                g.check_and_debit("k", 0.1, limit_usd=1.0),
                g.check_and_debit("k", 0.1, limit_usd=1.0),
            )

        asyncio.run(_contended_debits())  # loop 1 — binds lock._loop to loop 1
        asyncio.run(_contended_debits())  # loop 2 — RuntimeError BEFORE fix, OK after
