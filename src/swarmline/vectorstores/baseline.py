"""InMemoryVectorStore — dependency-free baseline VectorStore (rag-protocols-foundation, Task 3).

Namespaced, metadata-filterable, cosine-similarity vector store backed by a
plain ``dict``. Reuses ``skills.embedding_retriever._cosine_similarity`` (DRY
— same tolerant, zero-norm-safe similarity already used for skill
retrieval) so similarity math stays consistent across the codebase.

Covers REQ-009..013, 017: namespace isolation, metadata filtering, nearest-
first ranking with ``top_k``, idempotent upsert-by-id, zero external
dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from swarmline.protocols.rag import VectorMatch, VectorRecord
from swarmline.skills.embedding_retriever import _cosine_similarity


def _matches_filter(
    metadata: Mapping[str, Any], filter_: Mapping[str, Any] | None
) -> bool:
    """True if *metadata* satisfies every key/value pair in *filter_*.

    A record missing a filter key is excluded (non-match) — pinned decision.
    """
    if filter_ is None:
        return True
    return all(
        key in metadata and metadata[key] == value for key, value in filter_.items()
    )


class InMemoryVectorStore:
    """Baseline VectorStore: namespaced dict of id -> VectorRecord, zero deps.

    Implements the ``VectorStore`` Protocol (upsert/query/delete).
    """

    def __init__(self) -> None:
        self._ns: dict[str, dict[str, VectorRecord]] = {}

    async def upsert(
        self, records: Sequence[VectorRecord], *, namespace: str = ""
    ) -> None:
        """Insert or overwrite *records* by id within *namespace* (idempotent)."""
        bucket = self._ns.setdefault(namespace, {})
        for record in records:
            bucket[record.id] = replace(record, embedding=tuple(record.embedding))

    async def query(
        self,
        embedding: Sequence[float],
        *,
        top_k: int = 5,
        namespace: str = "",
        filter: Mapping[str, Any] | None = None,  # noqa: A002
    ) -> list[VectorMatch]:
        """Return the top-``top_k`` records in *namespace* by cosine similarity.

        Dimension mismatch never raises (B-DP2) — ``_cosine_similarity`` uses
        ``zip(strict=False)`` internally.
        """
        query_vec = list(embedding)
        candidates = [
            record
            for record in self._ns.get(namespace, {}).values()
            if _matches_filter(record.metadata, filter)
        ]
        scored = [
            (record, _cosine_similarity(query_vec, list(record.embedding)))
            for record in candidates
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [
            VectorMatch(
                id=record.id, score=score, text=record.text, metadata=record.metadata
            )
            for record, score in scored[:top_k]
        ]

    async def delete(self, ids: Sequence[str], *, namespace: str = "") -> int:
        """Remove *ids* present in *namespace*; return the count actually removed."""
        bucket = self._ns.get(namespace, {})
        removed = 0
        for record_id in ids:
            if bucket.pop(record_id, None) is not None:
                removed += 1
        return removed
