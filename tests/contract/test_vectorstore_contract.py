"""VectorStore Protocol contract tests (rag-protocols-foundation, Task 3).

Parametrized over vector-store implementation names (currently only
"inmemory" — ``InMemoryVectorStore``) so that any FUTURE store registered in
the ``store`` fixture must pass the same contract (contract-first: tests
pass for ANY correct implementation, not just the baseline).
"""

from __future__ import annotations

import pytest
from swarmline.protocols import VectorRecord, VectorStore
from swarmline.vectorstores import InMemoryVectorStore

_STORES: dict[str, type[VectorStore]] = {
    "inmemory": InMemoryVectorStore,
}


@pytest.fixture(params=list(_STORES))
def store(request: pytest.FixtureRequest) -> VectorStore:
    return _STORES[request.param]()


class TestVectorStoreProtocolShape:
    def test_vectorstore_protocol_shape(self, store: VectorStore) -> None:
        assert isinstance(store, VectorStore)


class TestUpsertAndQuery:
    async def test_upsert_then_query_returns_nearest_first(
        self, store: VectorStore
    ) -> None:
        records = [
            VectorRecord(id="near", embedding=[1.0, 0.0], text="near"),
            VectorRecord(id="far", embedding=[0.0, 1.0], text="far"),
        ]
        await store.upsert(records)

        matches = await store.query([1.0, 0.01])

        assert matches[0].id == "near"
        for earlier, later in zip(matches, matches[1:], strict=False):
            assert earlier.score >= later.score

    async def test_query_top_k_limits_results(self, store: VectorStore) -> None:
        records = [
            VectorRecord(id=f"r{i}", embedding=[float(i), 1.0]) for i in range(5)
        ]
        await store.upsert(records)

        matches = await store.query([1.0, 1.0], top_k=2)

        assert len(matches) == 2


class TestNamespaceIsolation:
    async def test_namespace_isolation(self, store: VectorStore) -> None:
        await store.upsert([VectorRecord(id="a1", embedding=[1.0, 0.0])], namespace="a")
        await store.upsert([VectorRecord(id="b1", embedding=[1.0, 0.0])], namespace="b")

        matches_b = await store.query([1.0, 0.0], namespace="b")

        assert [m.id for m in matches_b] == ["b1"]


class TestMetadataFilter:
    async def test_metadata_filter_restricts_matches(self, store: VectorStore) -> None:
        await store.upsert(
            [
                VectorRecord(id="py", embedding=[1.0, 0.0], metadata={"lang": "py"}),
                VectorRecord(id="js", embedding=[1.0, 0.0], metadata={"lang": "js"}),
                VectorRecord(id="nolang", embedding=[1.0, 0.0], metadata={}),
            ]
        )

        matches = await store.query([1.0, 0.0], filter={"lang": "py"})

        assert [m.id for m in matches] == ["py"]


class TestUpsertOverwrite:
    async def test_upsert_same_id_overwrites_no_duplicate(
        self, store: VectorStore
    ) -> None:
        await store.upsert([VectorRecord(id="x", embedding=[1.0, 0.0], text="v1")])
        await store.upsert([VectorRecord(id="x", embedding=[1.0, 0.0], text="v2")])

        matches = await store.query([1.0, 0.0], top_k=10)

        assert len(matches) == 1
        assert matches[0].text == "v2"


class TestDeleteAndEmpty:
    async def test_delete_removes_records_returns_count(
        self, store: VectorStore
    ) -> None:
        await store.upsert(
            [
                VectorRecord(id="a", embedding=[1.0, 0.0]),
                VectorRecord(id="b", embedding=[0.0, 1.0]),
            ]
        )

        removed = await store.delete(["a", "missing"])

        assert removed == 1
        matches = await store.query([1.0, 0.0], top_k=10)
        assert [m.id for m in matches] == ["b"]

    async def test_query_empty_store_returns_empty(self, store: VectorStore) -> None:
        matches = await store.query([1.0, 0.0])
        assert matches == []


class TestDimensionMismatchTolerance:
    async def test_query_dim_mismatch_does_not_raise(self, store: VectorStore) -> None:
        await store.upsert([VectorRecord(id="a", embedding=[1.0, 0.0, 0.0])])

        matches = await store.query([1.0, 0.0])

        assert isinstance(matches, list)
