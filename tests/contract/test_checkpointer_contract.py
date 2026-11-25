"""Contract tests for ``Checkpointer`` — shared across all implementations.

Parametrized fixture: any implementation added here must pass every
scenario below. ``inmemory`` (Task 2) and ``sqlite`` (Task 3) both wire in.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest
from swarmline.protocols import Checkpointer
from swarmline.session import InMemoryCheckpointer, SqliteCheckpointer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=["inmemory", "sqlite"])
async def checkpointer(request, tmp_path):
    if request.param == "inmemory":
        instance = InMemoryCheckpointer()
    elif request.param == "sqlite":
        instance = SqliteCheckpointer(str(tmp_path / "cp.db"))
    else:
        raise ValueError(
            f"Unknown checkpointer param: {request.param}"
        )  # pragma: no cover
    yield instance
    await instance.close()


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


class TestProtocolShape:
    def test_checkpointer_protocol_shape_inmemory(self) -> None:
        assert isinstance(InMemoryCheckpointer(), Checkpointer)


# ---------------------------------------------------------------------------
# put / get
# ---------------------------------------------------------------------------


class TestPutGet:
    async def test_put_then_get_latest_returns_last_state(self, checkpointer) -> None:
        thread_id = "thread-1"
        await checkpointer.put(thread_id, {"step": 1})
        await checkpointer.put(thread_id, {"step": 2})

        latest = await checkpointer.get(thread_id)

        assert latest is not None
        assert latest.state == {"step": 2}

    async def test_get_by_checkpoint_id_returns_that_checkpoint(
        self, checkpointer
    ) -> None:
        thread_id = "thread-2"
        first_id = await checkpointer.put(thread_id, {"step": 1})
        await checkpointer.put(thread_id, {"step": 2})

        first = await checkpointer.get(thread_id, checkpoint_id=first_id)

        assert first is not None
        assert first.id == first_id
        assert first.state == {"step": 1}

    async def test_get_missing_thread_returns_none(self, checkpointer) -> None:
        result = await checkpointer.get("no-such-thread")
        assert result is None

    async def test_put_returns_unique_ids(self, checkpointer) -> None:
        thread_id = "thread-3"
        id_a = await checkpointer.put(thread_id, {"step": 1})
        id_b = await checkpointer.put(thread_id, {"step": 2})
        assert id_a != id_b

    async def test_resource_id_round_trips(self, checkpointer) -> None:
        thread_id = "thread-4"
        cid = await checkpointer.put(thread_id, {"step": 1}, resource_id="user-42")

        cp = await checkpointer.get(thread_id, checkpoint_id=cid)

        assert cp is not None
        assert cp.resource_id == "user-42"


# ---------------------------------------------------------------------------
# list / lineage / history
# ---------------------------------------------------------------------------


class TestListLineage:
    async def test_list_returns_history_oldest_first_preserves_parent_id(
        self, checkpointer
    ) -> None:
        thread_id = "thread-5"
        first_id = await checkpointer.put(thread_id, {"step": 1})
        second_id = await checkpointer.put(thread_id, {"step": 2}, parent_id=first_id)

        history = await checkpointer.list(thread_id)

        assert [meta.id for meta in history] == [first_id, second_id]
        assert history[1].parent_id == first_id
        assert history[0].parent_id is None

    async def test_put_with_parent_id_persists_lineage(self, checkpointer) -> None:
        thread_id = "thread-6"
        parent_id = await checkpointer.put(thread_id, {"step": 1})
        child_id = await checkpointer.put(thread_id, {"step": 2}, parent_id=parent_id)

        child = await checkpointer.get(thread_id, checkpoint_id=child_id)

        assert child is not None
        assert child.parent_id == parent_id

    async def test_put_duplicate_checkpoint_id_appends_not_overwrites(
        self, checkpointer
    ) -> None:
        thread_id = "thread-7"
        await checkpointer.put(thread_id, {"step": 1}, checkpoint_id="fixed-id")
        await checkpointer.put(thread_id, {"step": 2}, checkpoint_id="fixed-id")

        history = await checkpointer.list(thread_id)

        assert len(history) == 2
        assert all(meta.id == "fixed-id" for meta in history)


# ---------------------------------------------------------------------------
# Copy semantics (no aliasing)
# ---------------------------------------------------------------------------


class TestCopySemantics:
    async def test_put_copies_state_no_aliasing(self, checkpointer) -> None:
        thread_id = "thread-8"
        mutable_state = {"step": 1}

        cid = await checkpointer.put(thread_id, mutable_state)
        mutable_state["step"] = 999
        mutable_state["extra"] = "added-after-put"

        stored = await checkpointer.get(thread_id, checkpoint_id=cid)

        assert stored is not None
        assert stored.state == {"step": 1}

    async def test_get_returns_defensive_copy_no_stored_mutation(
        self, checkpointer
    ) -> None:
        thread_id = "thread-11"
        cid = await checkpointer.put(
            thread_id, {"step": 1}, metadata={"tag": "original"}
        )

        cp = await checkpointer.get(thread_id, checkpoint_id=cid)
        assert cp is not None
        cp.state["mutated"] = "yes"
        cp.metadata["mutated"] = "yes"

        fresh = await checkpointer.get(thread_id, checkpoint_id=cid)
        assert fresh is not None
        assert fresh.state == {"step": 1}
        assert fresh.metadata == {"tag": "original"}

        history = await checkpointer.list(thread_id)
        assert history[0].metadata == {"tag": "original"}


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_delete_whole_thread_removes_all(self, checkpointer) -> None:
        thread_id = "thread-9"
        await checkpointer.put(thread_id, {"step": 1})
        await checkpointer.put(thread_id, {"step": 2})

        deleted = await checkpointer.delete(thread_id)

        assert deleted == 2
        assert await checkpointer.list(thread_id) == []
        assert await checkpointer.get(thread_id) is None

    async def test_delete_by_checkpoint_id_removes_one(self, checkpointer) -> None:
        thread_id = "thread-10"
        first_id = await checkpointer.put(thread_id, {"step": 1})
        await checkpointer.put(thread_id, {"step": 2})

        deleted = await checkpointer.delete(thread_id, checkpoint_id=first_id)

        assert deleted == 1
        remaining = await checkpointer.list(thread_id)
        assert len(remaining) == 1
        assert remaining[0].id != first_id

    async def test_delete_by_duplicate_checkpoint_id_removes_all_versions(
        self, checkpointer
    ) -> None:
        thread_id = "thread-12"
        await checkpointer.put(thread_id, {"step": 1}, checkpoint_id="dup-id")
        await checkpointer.put(thread_id, {"step": 2}, checkpoint_id="dup-id")

        deleted = await checkpointer.delete(thread_id, checkpoint_id="dup-id")

        assert deleted == 2
        remaining = await checkpointer.list(thread_id)
        assert all(meta.id != "dup-id" for meta in remaining)


# ---------------------------------------------------------------------------
# SQLite-specific (durability + append-only invariants that only bite a
# durable backend — the in-memory implementation cannot violate these)
# ---------------------------------------------------------------------------


class TestSqliteSpecific:
    async def test_sqlite_checkpointer_persists_across_instances(
        self, tmp_path
    ) -> None:
        db_path = str(tmp_path / "persist.db")
        thread_id = "thread-persist"

        first = SqliteCheckpointer(db_path)
        cid = await first.put(thread_id, {"step": 1})
        await first.close()

        second = SqliteCheckpointer(db_path)
        try:
            cp = await second.get(thread_id, checkpoint_id=cid)
            assert cp is not None
            assert cp.state == {"step": 1}
        finally:
            await second.close()

    async def test_sqlite_duplicate_checkpoint_id_still_appends(self, tmp_path) -> None:
        db_path = str(tmp_path / "dup.db")
        thread_id = "thread-dup"

        store = SqliteCheckpointer(db_path)
        try:
            await store.put(thread_id, {"step": 1}, checkpoint_id="fixed-id")
            await store.put(thread_id, {"step": 2}, checkpoint_id="fixed-id")

            history = await store.list(thread_id)

            assert len(history) == 2
            assert all(meta.id == "fixed-id" for meta in history)
        finally:
            await store.close()

    async def test_sqlite_defers_connection_until_first_use(self, tmp_path) -> None:
        db_path = tmp_path / "deferred.db"
        store = SqliteCheckpointer(str(db_path))
        try:
            assert store._conn is None
            assert not db_path.exists()

            await store.put("thread-defer", {"step": 1})

            assert store._conn is not None
            assert db_path.exists()
        finally:
            await store.close()

    async def test_sqlite_close_is_idempotent(self, tmp_path) -> None:
        db_path = str(tmp_path / "idempotent.db")
        store = SqliteCheckpointer(db_path)
        cid = await store.put("thread-idem", {"step": 1})

        await store.close()
        await store.close()  # must not raise

        fresh = await store.get("thread-idem", checkpoint_id=cid)
        assert fresh is not None
        assert fresh.state == {"step": 1}
        await store.close()

    async def test_sqlite_close_before_first_use_does_not_raise(self, tmp_path) -> None:
        store = SqliteCheckpointer(str(tmp_path / "never-used.db"))
        await store.close()
        await store.close()


# ---------------------------------------------------------------------------
# Concurrency (every implementation must preserve append integrity under
# concurrent puts — parametrized so SqliteCheckpointer inherits it in Task 3)
# ---------------------------------------------------------------------------


class TestConcurrency:
    async def test_concurrent_put_preserves_all_under_gather(
        self, checkpointer
    ) -> None:
        thread_id = "thread-concurrent"

        await asyncio.gather(
            *(checkpointer.put(thread_id, {"i": i}) for i in range(20))
        )

        history = await checkpointer.list(thread_id)
        assert len(history) == 20
        assert len({meta.id for meta in history}) == 20


# ---------------------------------------------------------------------------
# Non-overlap boundary (REQ-017/018) — enforced as assertions, not just prose
# ---------------------------------------------------------------------------

# Literal fallback for Python versions where Protocol.__protocol_attrs__ is
# unavailable (added in 3.12); always matches the pinned interface.
_CHECKPOINTER_METHODS_FALLBACK = frozenset({"put", "get", "list", "delete"})


def _protocol_methods(protocol_cls: type, fallback: frozenset[str]) -> frozenset[str]:
    return frozenset(getattr(protocol_cls, "__protocol_attrs__", fallback))


class TestNonOverlapBoundary:
    def test_checkpoint_module_does_not_import_resilience(self) -> None:
        import swarmline.protocols.checkpoint as checkpoint_module

        source = Path(checkpoint_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)

        referenced: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                referenced.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                referenced.add(node.module)

        assert not any("resilience" in name for name in referenced), (
            f"protocols/checkpoint.py must never import resilience.*: {referenced}"
        )

    def test_checkpointer_methods_disjoint_from_event_journal(self) -> None:
        from swarmline.observability.journal import EventJournal

        checkpointer_methods = _protocol_methods(
            Checkpointer, _CHECKPOINTER_METHODS_FALLBACK
        )
        journal_methods = _protocol_methods(
            EventJournal, frozenset({"append", "last_seq"})
        )

        assert checkpointer_methods.isdisjoint(journal_methods)

    def test_checkpointer_methods_disjoint_from_replay_reader(self) -> None:
        from swarmline.observability.journal import ReplayReader

        checkpointer_methods = _protocol_methods(
            Checkpointer, _CHECKPOINTER_METHODS_FALLBACK
        )
        reader_methods = _protocol_methods(ReplayReader, frozenset({"read"}))

        assert checkpointer_methods.isdisjoint(reader_methods)

    def test_checkpointer_methods_disjoint_from_resilience_checkpoint_port(
        self,
    ) -> None:
        from swarmline.resilience.checkpoint import CheckpointPort

        checkpointer_methods = _protocol_methods(
            Checkpointer, _CHECKPOINTER_METHODS_FALLBACK
        )
        checkpoint_port_methods = _protocol_methods(
            CheckpointPort,
            frozenset(
                {
                    "save_checkpoint",
                    "load_checkpoint",
                    "clear_checkpoint",
                    "list_orphaned",
                }
            ),
        )

        assert checkpointer_methods.isdisjoint(checkpoint_port_methods)

    def test_checkpoint_module_docstring_names_both_boundaries(self) -> None:
        import swarmline.protocols.checkpoint as checkpoint_module

        docstring = checkpoint_module.__doc__ or ""

        assert "EventJournal" in docstring
        assert "CheckpointPort" in docstring or "resilience" in docstring
