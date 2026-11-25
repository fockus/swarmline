"""RAG domain protocols and value objects (rag-protocols-foundation, Task 1).

Scope boundary (REQ-020): this module is a *zero-dependency foundation*
only — the 3 value objects and 3 Protocols (Embedder, VectorStore,
Reranker). Vendor adapters (OpenAI/Cohere/pgvector/etc.) and their
``pyproject.toml`` extras are explicitly deferred to a later spec; nothing
here reaches for an optional dependency.

This module does NOT modify the legacy ``swarmline.rag`` module
(Document/Retriever/SimpleRetriever) or ``swarmline.skills.embedding_retriever``
(REQ-018) — those retrieval paths stay untouched; this is a parallel,
lower-level set of ports that future vendor adapters implement against.

Pure domain layer: ``dataclasses`` + ``typing`` + ``collections.abc`` only,
zero external dependencies. Each Protocol is ISP-compliant (<=5 methods)
and ``@runtime_checkable`` so ``isinstance`` checks work for any conforming
implementation — the essence of contract-first design.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class VectorRecord:
    """A document chunk plus its embedding, ready to upsert into a VectorStore."""

    id: str
    embedding: Sequence[float]
    text: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorMatch:
    """A single similarity-search result returned by ``VectorStore.query``."""

    id: str
    score: float
    text: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RankedDocument:
    """A single reranked result, preserving the original candidate's index."""

    index: int
    score: float
    text: str


@runtime_checkable
class Embedder(Protocol):
    """Turns text into vectors. ISP: 3 methods (query, batch docs, token count)."""

    async def embed_query(self, text: str) -> list[float]: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def count_tokens(self, text: str) -> int: ...


@runtime_checkable
class VectorStore(Protocol):
    """Persists and retrieves VectorRecords. ISP: 3 methods (upsert/query/delete)."""

    async def upsert(
        self, records: Sequence[VectorRecord], *, namespace: str = ""
    ) -> None: ...

    async def query(
        self,
        embedding: Sequence[float],
        *,
        top_k: int = 5,
        namespace: str = "",
        filter: Mapping[str, Any] | None = None,  # noqa: A002
    ) -> list[VectorMatch]: ...

    async def delete(self, ids: Sequence[str], *, namespace: str = "") -> int: ...


@runtime_checkable
class Reranker(Protocol):
    """Reorders candidate documents by relevance to a query. ISP: 1 method."""

    async def rerank(
        self, query: str, documents: Sequence[str], *, top_k: int | None = None
    ) -> list[RankedDocument]: ...
