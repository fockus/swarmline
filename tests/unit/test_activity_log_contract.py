"""Contract tests for ActivityLog — parametrized over InMemory and SQLite backends."""

from __future__ import annotations

import time

import pytest

from cognitia.observability.activity_types import ActivityEntry, ActivityFilter, ActorType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=["inmemory", "sqlite"])
def log(request, tmp_path):
    if request.param == "inmemory":
        from cognitia.observability.activity_log import InMemoryActivityLog

        return InMemoryActivityLog()
    else:
        from cognitia.observability.activity_log import SqliteActivityLog

        return SqliteActivityLog(str(tmp_path / "test.db"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(
    id: str = "e1",
    actor_type: ActorType = ActorType.AGENT,
    actor_id: str = "agent-1",
    action: str = "task.created",
    entity_type: str = "task",
    entity_id: str = "t-1",
    details: dict | None = None,
    timestamp: float | None = None,
) -> ActivityEntry:
    return ActivityEntry(
        id=id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
        timestamp=timestamp or time.time(),
    )


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


class TestProtocolShape:

    def test_protocol_shape(self, log) -> None:
        from cognitia.observability.activity_log import ActivityLog

        assert isinstance(log, ActivityLog)


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------


class TestBasicCRUD:

    async def test_log_and_query_all(self, log) -> None:
        """Log 3 entries, query with empty filter returns all."""
        await log.log(_entry(id="e1", timestamp=3.0))
        await log.log(_entry(id="e2", timestamp=2.0))
        await log.log(_entry(id="e3", timestamp=1.0))

        results = await log.query(ActivityFilter())
        assert len(results) == 3
        # Sorted by timestamp descending
        assert results[0].id == "e1"
        assert results[1].id == "e2"
        assert results[2].id == "e3"

    async def test_empty_log_returns_empty_list(self, log) -> None:
        results = await log.query(ActivityFilter())
        assert results == []


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class TestFiltering:

    async def test_query_by_actor_type(self, log) -> None:
        await log.log(_entry(id="e1", actor_type=ActorType.AGENT))
        await log.log(_entry(id="e2", actor_type=ActorType.USER))
        await log.log(_entry(id="e3", actor_type=ActorType.AGENT))

        results = await log.query(ActivityFilter(actor_type=ActorType.AGENT))
        assert len(results) == 2
        assert all(r.actor_type == ActorType.AGENT for r in results)

    async def test_query_by_actor_id(self, log) -> None:
        await log.log(_entry(id="e1", actor_id="agent-1"))
        await log.log(_entry(id="e2", actor_id="agent-2"))

        results = await log.query(ActivityFilter(actor_id="agent-1"))
        assert len(results) == 1
        assert results[0].actor_id == "agent-1"

    async def test_query_by_entity_id(self, log) -> None:
        await log.log(_entry(id="e1", entity_id="t-1"))
        await log.log(_entry(id="e2", entity_id="t-2"))
        await log.log(_entry(id="e3", entity_id="t-1"))

        results = await log.query(ActivityFilter(entity_id="t-1"))
        assert len(results) == 2
        assert all(r.entity_id == "t-1" for r in results)

    async def test_query_by_action(self, log) -> None:
        await log.log(_entry(id="e1", action="task.created"))
        await log.log(_entry(id="e2", action="budget.exceeded"))
        await log.log(_entry(id="e3", action="task.created"))

        results = await log.query(ActivityFilter(action="task.created"))
        assert len(results) == 2
        assert all(r.action == "task.created" for r in results)

    async def test_query_by_time_range(self, log) -> None:
        await log.log(_entry(id="e1", timestamp=100.0))
        await log.log(_entry(id="e2", timestamp=200.0))
        await log.log(_entry(id="e3", timestamp=300.0))

        results = await log.query(ActivityFilter(since=150.0, until=250.0))
        assert len(results) == 1
        assert results[0].id == "e2"

    async def test_query_by_time_range_since_only(self, log) -> None:
        await log.log(_entry(id="e1", timestamp=100.0))
        await log.log(_entry(id="e2", timestamp=200.0))
        await log.log(_entry(id="e3", timestamp=300.0))

        results = await log.query(ActivityFilter(since=200.0))
        assert len(results) == 2
        ids = {r.id for r in results}
        assert ids == {"e2", "e3"}

    async def test_query_by_time_range_until_only(self, log) -> None:
        await log.log(_entry(id="e1", timestamp=100.0))
        await log.log(_entry(id="e2", timestamp=200.0))
        await log.log(_entry(id="e3", timestamp=300.0))

        results = await log.query(ActivityFilter(until=200.0))
        assert len(results) == 2
        ids = {r.id for r in results}
        assert ids == {"e1", "e2"}

    async def test_query_combined_filters(self, log) -> None:
        await log.log(_entry(
            id="e1", actor_type=ActorType.AGENT, action="task.created",
            entity_type="task", timestamp=100.0,
        ))
        await log.log(_entry(
            id="e2", actor_type=ActorType.USER, action="task.created",
            entity_type="task", timestamp=200.0,
        ))
        await log.log(_entry(
            id="e3", actor_type=ActorType.AGENT, action="budget.exceeded",
            entity_type="pipeline", timestamp=300.0,
        ))

        results = await log.query(ActivityFilter(
            actor_type=ActorType.AGENT, action="task.created",
        ))
        assert len(results) == 1
        assert results[0].id == "e1"

    async def test_query_by_entity_type(self, log) -> None:
        await log.log(_entry(id="e1", entity_type="task"))
        await log.log(_entry(id="e2", entity_type="pipeline"))

        results = await log.query(ActivityFilter(entity_type="task"))
        assert len(results) == 1
        assert results[0].entity_type == "task"


# ---------------------------------------------------------------------------
# Count
# ---------------------------------------------------------------------------


class TestCount:

    async def test_count_matches_query_length(self, log) -> None:
        await log.log(_entry(id="e1", actor_type=ActorType.AGENT))
        await log.log(_entry(id="e2", actor_type=ActorType.USER))
        await log.log(_entry(id="e3", actor_type=ActorType.AGENT))

        f = ActivityFilter(actor_type=ActorType.AGENT)
        query_results = await log.query(f)
        count = await log.count(f)
        assert count == len(query_results) == 2

    async def test_count_empty(self, log) -> None:
        count = await log.count(ActivityFilter())
        assert count == 0

    async def test_count_all(self, log) -> None:
        await log.log(_entry(id="e1"))
        await log.log(_entry(id="e2"))
        count = await log.count(ActivityFilter())
        assert count == 2


# ---------------------------------------------------------------------------
# Details preservation
# ---------------------------------------------------------------------------


class TestDetails:

    async def test_details_round_trip(self, log) -> None:
        details = {"reason": "budget exceeded", "amount": 42.5, "tags": ["a", "b"]}
        await log.log(_entry(id="e1", details=details))

        results = await log.query(ActivityFilter())
        assert results[0].details == details


# ---------------------------------------------------------------------------
# Eviction (bounded growth)
# ---------------------------------------------------------------------------


class TestEviction:

    async def test_activity_log_evicts_when_over_max_inmemory(self) -> None:
        """InMemoryActivityLog with max_entries=5: append 7, verify only 5 remain."""
        from cognitia.observability.activity_log import InMemoryActivityLog

        log = InMemoryActivityLog(max_entries=5)
        for i in range(7):
            await log.log(_entry(id=f"e{i}", timestamp=float(i + 1)))

        count = await log.count(ActivityFilter())
        assert count == 5
        # Oldest entries (e0, e1) should be evicted; newest 5 remain
        results = await log.query(ActivityFilter())
        ids = {r.id for r in results}
        assert ids == {"e2", "e3", "e4", "e5", "e6"}

    async def test_activity_log_evicts_when_over_max_sqlite(self, tmp_path) -> None:
        """SqliteActivityLog with max_entries=5: append 7, verify only 5 remain."""
        from cognitia.observability.activity_log import SqliteActivityLog

        log = SqliteActivityLog(str(tmp_path / "evict.db"), max_entries=5)
        for i in range(7):
            await log.log(_entry(id=f"e{i}", timestamp=float(i + 1)))

        count = await log.count(ActivityFilter())
        assert count == 5
        # Oldest entries (e0, e1) should be evicted; newest 5 remain
        results = await log.query(ActivityFilter())
        ids = {r.id for r in results}
        assert ids == {"e2", "e3", "e4", "e5", "e6"}
        log.close()

    async def test_activity_log_no_eviction_when_under_max(self) -> None:
        """When entries < max_entries, nothing is evicted."""
        from cognitia.observability.activity_log import InMemoryActivityLog

        log = InMemoryActivityLog(max_entries=10)
        for i in range(5):
            await log.log(_entry(id=f"e{i}", timestamp=float(i + 1)))

        count = await log.count(ActivityFilter())
        assert count == 5

    async def test_sqlite_count_uses_sql_count(self, tmp_path) -> None:
        """SqliteActivityLog.count() returns correct result (should use SQL COUNT)."""
        from cognitia.observability.activity_log import SqliteActivityLog

        log = SqliteActivityLog(str(tmp_path / "count.db"))
        for i in range(20):
            await log.log(_entry(
                id=f"e{i}",
                actor_type=ActorType.AGENT if i % 2 == 0 else ActorType.USER,
                timestamp=float(i),
            ))

        total = await log.count(ActivityFilter())
        assert total == 20
        agent_count = await log.count(ActivityFilter(actor_type=ActorType.AGENT))
        assert agent_count == 10
        log.close()
