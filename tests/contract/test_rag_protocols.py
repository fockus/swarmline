"""Structural contract tests for RAG domain protocols (rag-protocols-foundation, Task 1).

Verifies:
    - The 3 value objects (VectorRecord, VectorMatch, RankedDocument) are frozen
      dataclasses (REQ-004).
    - All 6 symbols are importable from ``swarmline.protocols`` (public re-export).
    - Minimal inline fake classes satisfy the 3 Protocols structurally via
      ``isinstance`` — this is the essence of contract-first: any correct
      implementation (not just the baselines) must pass these checks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError
from typing import Any

import pytest
from swarmline.protocols import (
    Embedder,
    RankedDocument,
    Reranker,
    VectorMatch,
    VectorRecord,
    VectorStore,
)


class TestValueObjectsFrozen:
    """REQ-004: value objects must be immutable frozen dataclasses."""

    def test_rag_value_types_are_frozen(self) -> None:
        record = VectorRecord(id="1", embedding=[0.1, 0.2])
        match = VectorMatch(id="1", score=0.9)
        ranked = RankedDocument(index=0, score=0.5, text="hello")

        with pytest.raises(FrozenInstanceError):
            record.id = "2"  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            match.score = 0.1  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            ranked.text = "bye"  # type: ignore[misc]


class TestImportableFromSwarmlineProtocols:
    def test_rag_protocols_importable_from_swarmline_protocols(self) -> None:
        import swarmline.protocols as protocols_pkg

        for name in (
            "Embedder",
            "VectorStore",
            "Reranker",
            "VectorRecord",
            "VectorMatch",
            "RankedDocument",
        ):
            assert hasattr(protocols_pkg, name), (
                f"{name} missing from swarmline.protocols"
            )
            assert name in protocols_pkg.__all__, f"{name} missing from __all__"


class _FakeEmbedder:
    """Minimal inline fake satisfying the Embedder Protocol structurally."""

    async def embed_query(self, text: str) -> list[float]:
        return [0.0]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def count_tokens(self, text: str) -> int:
        return len(text.split())


class _FakeVectorStore:
    """Minimal inline fake satisfying the VectorStore Protocol structurally."""

    async def upsert(
        self, records: Sequence[VectorRecord], *, namespace: str = ""
    ) -> None:
        return None

    async def query(
        self,
        embedding: Sequence[float],
        *,
        top_k: int = 5,
        namespace: str = "",
        filter: Mapping[str, Any] | None = None,  # noqa: A002
    ) -> list[VectorMatch]:
        return []

    async def delete(self, ids: Sequence[str], *, namespace: str = "") -> int:
        return 0


class _FakeReranker:
    """Minimal inline fake satisfying the Reranker Protocol structurally."""

    async def rerank(
        self, query: str, documents: Sequence[str], *, top_k: int | None = None
    ) -> list[RankedDocument]:
        return [
            RankedDocument(index=i, score=1.0, text=doc)
            for i, doc in enumerate(documents)
        ]


class TestInlineFakesSatisfyProtocols:
    def test_inline_fake_satisfies_embedder_protocol(self) -> None:
        assert isinstance(_FakeEmbedder(), Embedder)

    def test_inline_fake_satisfies_vectorstore_protocol(self) -> None:
        assert isinstance(_FakeVectorStore(), VectorStore)

    def test_inline_fake_satisfies_reranker_protocol(self) -> None:
        assert isinstance(_FakeReranker(), Reranker)
