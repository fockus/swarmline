"""Persistent budget store — cross-run budget tracking with time windows.

Provides:
- PersistentBudgetStore protocol (ISP: 4 methods)
- InMemoryPersistentBudgetStore — default, no external deps
- SqlitePersistentBudgetStore — zero-config file-based persistence
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from swarmline.pipeline.budget_types import (
    BudgetIncident,
    BudgetScope,
    BudgetScopeType,
    BudgetThreshold,
    BudgetWindow,
    CostEvent,
    ThresholdAction,
    ThresholdResult,
    _generate_id,
)


def _month_start_timestamp() -> float:
    """Return the Unix timestamp of the start of the current month (UTC-naive local)."""
    now = datetime.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


@runtime_checkable
class PersistentBudgetStore(Protocol):
    """Cross-run budget tracking with time windows. ISP: 4 methods."""

    async def record_cost(
        self, scope: BudgetScope, amount_usd: float, description: str = "",
    ) -> None: ...

    async def get_usage(self, scope: BudgetScope, window: BudgetWindow) -> float: ...

    async def check_threshold(
        self, scope: BudgetScope, window: BudgetWindow,
    ) -> ThresholdResult: ...

    async def list_incidents(self, scope: BudgetScope) -> list[BudgetIncident]: ...


# ---------------------------------------------------------------------------
# InMemory implementation
# ---------------------------------------------------------------------------


class InMemoryPersistentBudgetStore:
    """In-memory persistent budget store for testing and development."""

    def __init__(self, *, event_bus: Any | None = None) -> None:
        self._costs: list[CostEvent] = []
        self._thresholds: dict[tuple[str, str, str], BudgetThreshold] = {}
        self._incidents: list[BudgetIncident] = []
        self._bus = event_bus
        self._lock = asyncio.Lock()

    def register_threshold(self, threshold: BudgetThreshold) -> None:
        """Register a budget threshold for a scope + window. Not in protocol."""
        key = (
            threshold.scope.scope_type.value,
            threshold.scope.scope_id,
            threshold.window.value,
        )
        self._thresholds[key] = threshold

    async def record_cost(
        self, scope: BudgetScope, amount_usd: float, description: str = "",
    ) -> None:
        async with self._lock:
            event = CostEvent(
                id=_generate_id(),
                scope=scope,
                amount_usd=amount_usd,
                description=description,
            )
            self._costs.append(event)

    async def get_usage(self, scope: BudgetScope, window: BudgetWindow) -> float:
        async with self._lock:
            if window == BudgetWindow.MONTHLY:
                cutoff = _month_start_timestamp()
                return sum(
                    c.amount_usd
                    for c in self._costs
                    if c.scope == scope and c.timestamp >= cutoff
                )
            # LIFETIME
            return sum(
                c.amount_usd for c in self._costs if c.scope == scope
            )

    async def check_threshold(
        self, scope: BudgetScope, window: BudgetWindow,
    ) -> ThresholdResult:
        usage = await self.get_usage(scope, window)
        key = (scope.scope_type.value, scope.scope_id, window.value)
        threshold = self._thresholds.get(key)

        if threshold is None:
            return ThresholdResult(
                scope=scope,
                window=window,
                usage_usd=usage,
                limit_usd=0.0,
                percent=0.0,
                action=ThresholdAction.OK,
            )

        percent = (usage / threshold.limit_usd * 100.0) if threshold.limit_usd > 0 else 0.0

        if percent >= 100.0 and threshold.hard_stop:
            action = ThresholdAction.STOP
        elif percent >= threshold.warn_at_percent:
            action = ThresholdAction.WARN
        else:
            action = ThresholdAction.OK

        result = ThresholdResult(
            scope=scope,
            window=window,
            usage_usd=usage,
            limit_usd=threshold.limit_usd,
            percent=percent,
            action=action,
        )

        if action != ThresholdAction.OK:
            incident = BudgetIncident(
                id=_generate_id(),
                scope=scope,
                window=window,
                usage_usd=usage,
                limit_usd=threshold.limit_usd,
                action=action,
            )
            async with self._lock:
                self._incidents.append(incident)
            await self._emit_event(result)

        return result

    async def list_incidents(self, scope: BudgetScope) -> list[BudgetIncident]:
        async with self._lock:
            return [i for i in self._incidents if i.scope == scope]

    async def _emit_event(self, result: ThresholdResult) -> None:
        """Emit event bus notification on threshold breach."""
        if self._bus is None:
            return
        try:
            await self._bus.emit("pipeline.budget.threshold_exceeded", {
                "scope_type": result.scope.scope_type.value,
                "scope_id": result.scope.scope_id,
                "window": result.window.value,
                "usage_usd": result.usage_usd,
                "limit_usd": result.limit_usd,
                "percent": result.percent,
                "action": result.action.value,
            })
        except Exception:
            pass  # fire-and-forget


# ---------------------------------------------------------------------------
# SQLite implementation
# ---------------------------------------------------------------------------


_CREATE_SQL = """\
CREATE TABLE IF NOT EXISTS budget_costs (
    id TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    timestamp REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bc_scope
    ON budget_costs (scope_type, scope_id);

CREATE TABLE IF NOT EXISTS budget_thresholds (
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    window TEXT NOT NULL,
    limit_usd REAL NOT NULL,
    warn_at_percent REAL NOT NULL DEFAULT 80.0,
    hard_stop INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (scope_type, scope_id, window)
);

CREATE TABLE IF NOT EXISTS budget_incidents (
    id TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    window TEXT NOT NULL,
    usage_usd REAL NOT NULL,
    limit_usd REAL NOT NULL,
    action TEXT NOT NULL,
    timestamp REAL NOT NULL
);
"""


class SqlitePersistentBudgetStore:
    """SQLite-based persistent budget store.

    Uses asyncio.to_thread() to avoid blocking the event loop.
    WAL mode for concurrent read performance.
    """

    def __init__(
        self,
        db_path: str = "swarmline_budget.db",
        *,
        event_bus: Any | None = None,
    ) -> None:
        self._db_path = db_path
        self._bus = event_bus
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_CREATE_SQL)
        self._conn.commit()

    def register_threshold(self, threshold: BudgetThreshold) -> None:
        """Register a budget threshold for a scope + window. Not in protocol."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO budget_thresholds "
                "(scope_type, scope_id, window, limit_usd, warn_at_percent, hard_stop) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    threshold.scope.scope_type.value,
                    threshold.scope.scope_id,
                    threshold.window.value,
                    threshold.limit_usd,
                    threshold.warn_at_percent,
                    1 if threshold.hard_stop else 0,
                ),
            )
            self._conn.commit()

    # -- sync helpers (run in thread) --

    def _execute_sync(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def _record_cost_sync(
        self, cost_id: str, scope_type: str, scope_id: str,
        amount_usd: float, description: str, ts: float,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO budget_costs "
                "(id, scope_type, scope_id, amount_usd, description, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (cost_id, scope_type, scope_id, amount_usd, description, ts),
            )
            self._conn.commit()

    def _get_usage_sync(
        self, scope_type: str, scope_id: str, cutoff: float,
    ) -> float:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0.0) FROM budget_costs "
                "WHERE scope_type = ? AND scope_id = ? AND timestamp >= ?",
                (scope_type, scope_id, cutoff),
            )
            row = cursor.fetchone()
        return float(row[0]) if row else 0.0

    def _get_threshold_sync(
        self, scope_type: str, scope_id: str, window: str,
    ) -> BudgetThreshold | None:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT limit_usd, warn_at_percent, hard_stop "
                "FROM budget_thresholds "
                "WHERE scope_type = ? AND scope_id = ? AND window = ?",
                (scope_type, scope_id, window),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        scope = BudgetScope(
            scope_type=BudgetScopeType(scope_type),
            scope_id=scope_id,
        )
        return BudgetThreshold(
            scope=scope,
            window=BudgetWindow(window),
            limit_usd=float(row[0]),
            warn_at_percent=float(row[1]),
            hard_stop=bool(row[2]),
        )

    def _add_incident_sync(
        self, incident_id: str, scope_type: str, scope_id: str,
        window: str, usage_usd: float, limit_usd: float,
        action: str, ts: float,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO budget_incidents "
                "(id, scope_type, scope_id, window, usage_usd, limit_usd, action, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (incident_id, scope_type, scope_id, window, usage_usd, limit_usd, action, ts),
            )
            self._conn.commit()

    def _list_incidents_sync(
        self, scope_type: str, scope_id: str,
    ) -> list[BudgetIncident]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, scope_type, scope_id, window, usage_usd, limit_usd, action, timestamp "
                "FROM budget_incidents WHERE scope_type = ? AND scope_id = ? "
                "ORDER BY timestamp",
                (scope_type, scope_id),
            )
            rows = cursor.fetchall()
        return [
            BudgetIncident(
                id=r[0],
                scope=BudgetScope(
                    scope_type=BudgetScopeType(r[1]),
                    scope_id=r[2],
                ),
                window=BudgetWindow(r[3]),
                usage_usd=float(r[4]),
                limit_usd=float(r[5]),
                action=ThresholdAction(r[6]),
                timestamp=float(r[7]),
            )
            for r in rows
        ]

    # -- async API --

    async def record_cost(
        self, scope: BudgetScope, amount_usd: float, description: str = "",
    ) -> None:
        cost_id = _generate_id()
        ts = time.time()
        await asyncio.to_thread(
            self._record_cost_sync,
            cost_id, scope.scope_type.value, scope.scope_id,
            amount_usd, description, ts,
        )

    async def get_usage(self, scope: BudgetScope, window: BudgetWindow) -> float:
        if window == BudgetWindow.MONTHLY:
            cutoff = _month_start_timestamp()
        else:
            cutoff = 0.0
        return await asyncio.to_thread(
            self._get_usage_sync,
            scope.scope_type.value, scope.scope_id, cutoff,
        )

    async def check_threshold(
        self, scope: BudgetScope, window: BudgetWindow,
    ) -> ThresholdResult:
        usage = await self.get_usage(scope, window)
        threshold = await asyncio.to_thread(
            self._get_threshold_sync,
            scope.scope_type.value, scope.scope_id, window.value,
        )

        if threshold is None:
            return ThresholdResult(
                scope=scope,
                window=window,
                usage_usd=usage,
                limit_usd=0.0,
                percent=0.0,
                action=ThresholdAction.OK,
            )

        percent = (usage / threshold.limit_usd * 100.0) if threshold.limit_usd > 0 else 0.0

        if percent >= 100.0 and threshold.hard_stop:
            action = ThresholdAction.STOP
        elif percent >= threshold.warn_at_percent:
            action = ThresholdAction.WARN
        else:
            action = ThresholdAction.OK

        result = ThresholdResult(
            scope=scope,
            window=window,
            usage_usd=usage,
            limit_usd=threshold.limit_usd,
            percent=percent,
            action=action,
        )

        if action != ThresholdAction.OK:
            incident_id = _generate_id()
            ts = time.time()
            await asyncio.to_thread(
                self._add_incident_sync,
                incident_id, scope.scope_type.value, scope.scope_id,
                window.value, usage, threshold.limit_usd,
                action.value, ts,
            )
            await self._emit_event(result)

        return result

    async def list_incidents(self, scope: BudgetScope) -> list[BudgetIncident]:
        return await asyncio.to_thread(
            self._list_incidents_sync,
            scope.scope_type.value, scope.scope_id,
        )

    async def _emit_event(self, result: ThresholdResult) -> None:
        """Emit event bus notification on threshold breach."""
        if self._bus is None:
            return
        try:
            await self._bus.emit("pipeline.budget.threshold_exceeded", {
                "scope_type": result.scope.scope_type.value,
                "scope_id": result.scope.scope_id,
                "window": result.window.value,
                "usage_usd": result.usage_usd,
                "limit_usd": result.limit_usd,
                "percent": result.percent,
                "action": result.action.value,
            })
        except Exception:
            pass  # fire-and-forget

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            self._conn.close()
