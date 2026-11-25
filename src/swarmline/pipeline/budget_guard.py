"""Atomic check-and-debit guard layered over a PersistentBudgetStore.

Covers REQ-OSS-011: WHERE a budget guard is configured, the projected cost is
atomically checked-and-debited and the call refused if it would exceed the limit.

Additive and generic (REQ-OSS-050/051): a caller that never constructs a
BudgetGuard sees byte-identical store behaviour. Identifiers are plain ``str``
keys; amounts are in the store's native unit (USD float, BudgetScope). No
tenant/workspace/product types.

The store's record_cost/get_usage are individually serialized but the gap between
them is a TOCTOU window: two concurrent debits could both read a stale usage and
both pass a near-limit check. BudgetGuard closes that window by holding a single
asyncio.Lock across the read + check + debit so the operation is atomic.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from swarmline.pipeline.budget_store import PersistentBudgetStore
from swarmline.pipeline.budget_types import BudgetScope, BudgetScopeType, BudgetWindow

# Module-level registry: one asyncio.Lock per (store, event-loop) pair, shared across
# ALL BudgetGuard instances wrapping the same store in the same loop.  Atomicity must
# be at the shared resource boundary, not per guard.
# ponytail: dict keyed by id(store), value is (loop, Lock).  Never shrinks — one tiny
# entry per distinct store address.  id() works for ANY object regardless of hashability
# or weak-referenceability.  If the running loop differs from the cached entry the lock
# is rebound (fresh Lock for the new loop); a stale dead-loop entry is replaced on next
# access — no RuntimeError from cross-loop Lock reuse.  id() reuse after GC can only
# over-serialize two never-simultaneously-live stores, never under-serialize (atomicity
# always preserved).  Upgrade path: weakref.finalize cleanup if many short-lived stores.
_store_locks: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Lock]] = {}


def _get_store_lock(store: object) -> asyncio.Lock:
    """Return (or rebind) the shared asyncio.Lock for *store* in the running loop.

    Must be called from an async context (``asyncio.get_running_loop()`` must not
    raise).  No ``await`` between the check and the insert — race-free in
    single-threaded asyncio.  Within one loop two guards over the same store get the
    same Lock (cross-instance atomicity).  Across loops each loop gets a fresh Lock
    (no RuntimeError from ``_get_loop()`` on the contended acquire path).
    """
    loop = asyncio.get_running_loop()
    key = id(store)
    entry = _store_locks.get(key)
    if entry is None or entry[0] is not loop:
        lock = asyncio.Lock()
        _store_locks[key] = (loop, lock)
        return lock
    return entry[1]


@dataclass(frozen=True)
class DebitDecision:
    """Outcome of a check_and_debit attempt (USD)."""

    allowed: bool
    scope: BudgetScope
    usage_usd: float  # usage BEFORE this debit
    requested_usd: float
    projected_usd: float  # usage + requested
    limit_usd: float


class BudgetGuard:
    """Atomic check-and-debit over a PersistentBudgetStore (USD, BudgetScope)."""

    def __init__(
        self,
        store: PersistentBudgetStore,
        *,
        window: BudgetWindow = BudgetWindow.LIFETIME,
        scope_type: BudgetScopeType = BudgetScopeType.AGENT,
    ) -> None:
        self._store = store
        self._window = window
        self._scope_type = scope_type

    async def check_and_debit(
        self,
        key: str,
        amount_usd: float,
        *,
        limit_usd: float,
        description: str = "",
    ) -> DebitDecision:
        """Atomically check the projected usage against limit and debit if within.

        Returns a DebitDecision; allowed=False means the debit was refused and NOT
        recorded. Atomic under concurrency: the read + check + debit run under one
        lock so two near-limit debits cannot both pass.
        """
        scope = BudgetScope(scope_type=self._scope_type, scope_id=key)
        # Fetch the per-store lock for the running loop.  Called here (not in
        # __init__) so it always sees the correct loop and never reuses a lock
        # bound to a different (now-closed) loop.  No await before the lock
        # acquisition below — within-loop cross-instance atomicity preserved.
        lock = _get_store_lock(self._store)
        # Atomic: the read + check + debit run under one lock so two concurrent
        # near-limit debits cannot both pass the check (closes the TOCTOU window).
        async with lock:
            usage = await self._store.get_usage(scope, self._window)
            projected = usage + amount_usd
            if projected > limit_usd:
                return DebitDecision(
                    allowed=False,
                    scope=scope,
                    usage_usd=usage,
                    requested_usd=amount_usd,
                    projected_usd=projected,
                    limit_usd=limit_usd,
                )
            await self._store.record_cost(
                scope, amount_usd, description or f"check_and_debit:{key}"
            )
            return DebitDecision(
                allowed=True,
                scope=scope,
                usage_usd=usage,
                requested_usd=amount_usd,
                projected_usd=projected,
                limit_usd=limit_usd,
            )
