"""Pluggable RAG pipeline (chunk -> embed -> ``VectorStore`` -> optional
``Reranker``) + retriever + agent tool (Stage C2.4, Mastra parity).

SIBLING of ``swarmline.rag`` (Strangler-Fig, decision C-DP5): ``swarmline.rag``
(``Document``/``Retriever``/``SimpleRetriever``/``RagInputFilter``/
``TieredRetriever``) stays completely untouched. This module reuses
``rag.Document`` and satisfies ``rag.Retriever`` so ``VectorQueryRetriever``
drops straight into the existing ``RagInputFilter`` -- one pluggable
retrieval backend among several, not a replacement.

Built on the B2 protocols (``Embedder``/``VectorStore``/``Reranker``,
``swarmline.protocols.rag``); zero vendor installs needed for the offline
test suite (``HashEmbedder`` + ``InMemoryVectorStore`` + ``RRFReranker``).

Indexing always uses ``embed_documents`` (the DOCUMENT side of the
embedding space); querying always uses ``embed_query`` (the QUERY side) --
same asymmetric-embedder lesson as Stage C2.2's ``SemanticRecall``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING
from uuid import uuid4

from swarmline.agent.tool import tool
from swarmline.rag import Document

if TYPE_CHECKING:
    from swarmline.agent.tool_protocol import ToolFunction
    from swarmline.protocols.rag import Embedder, Reranker, VectorMatch, VectorStore


def chunk_text(text: str, *, max_chars: int = 1000, overlap: int = 100) -> list[str]:
    """Split ``text`` into chunks of at most ``max_chars``, each consecutive
    pair sharing ``overlap`` characters. Pure function.

    Empty ``text`` -> ``[]``. ``text`` no longer than ``max_chars`` -> one
    chunk. ``overlap >= max_chars`` is clamped to ``max_chars - 1`` (an
    infinite-loop guard -- the sliding-window step would otherwise be <= 0).
    A negative ``overlap`` is clamped to 0.
    """
    if not text.strip():
        return []  # whitespace-only docs would index blank zero-vector chunks
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    eff_overlap = max(0, min(overlap, max_chars - 1))
    if len(text) <= max_chars:
        return [text]

    step = max_chars - eff_overlap
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        chunks.append(text[start:end])
        if end >= n:
            break
        start += step
    return chunks


class RagPipeline:
    """Chunk -> embed -> ``VectorStore`` upsert/query -> optional ``Reranker``.

    ISP: 2 methods (``aindex``/``aquery``).
    """

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        *,
        reranker: Reranker | None = None,
        chunker: Callable[[str], list[str]] | None = None,
        namespace: str = "",
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._reranker = reranker
        self._chunker = chunker or chunk_text
        self._namespace = namespace

    async def aindex(
        self, documents: Sequence[Document | str], *, namespace: str | None = None
    ) -> int:
        """Chunk each document, ``embed_documents`` (DOCUMENT side) the
        chunks in one batch call, upsert them all, and return the total
        chunk count. Empty ``documents`` / all-empty-text documents -> 0,
        no upsert call at all."""
        from swarmline.protocols.rag import VectorRecord

        ns = self._namespace if namespace is None else namespace
        chunks: list[str] = []
        chunk_metadata: list[dict] = []
        for doc in documents:
            content = doc.content if isinstance(doc, Document) else doc
            metadata = dict(doc.metadata) if isinstance(doc, Document) else {}
            doc_chunks = self._chunker(content)
            chunks.extend(doc_chunks)
            chunk_metadata.extend(metadata for _ in doc_chunks)

        if not chunks:
            return 0

        vectors = await self._embedder.embed_documents(chunks)
        records = [
            VectorRecord(id=uuid4().hex, embedding=vector, text=chunk, metadata=meta)
            for chunk, vector, meta in zip(chunks, vectors, chunk_metadata, strict=True)
        ]
        await self._store.upsert(records, namespace=ns)
        return len(chunks)

    async def aquery(
        self,
        query: str,
        *,
        top_k: int = 5,
        namespace: str | None = None,
        rerank_top_k: int | None = None,
    ) -> list[Document]:
        """``embed_query`` -> ``store.query`` -> optional rerank -> ``Document``s.

        A whitespace-only ``query`` short-circuits to ``[]`` -- a zero
        vector would surface arbitrary records at score ~0 (C2.2 lesson).
        """
        query = query.strip()
        if not query:
            return []
        ns = self._namespace if namespace is None else namespace
        vector = await self._embedder.embed_query(query)
        matches = await self._store.query(vector, top_k=top_k, namespace=ns)
        if not matches:
            return []

        if self._reranker is not None:
            matches = await self._rerank(query, matches, rerank_top_k)

        return [
            Document(content=m.text, metadata=dict(m.metadata), score=m.score)
            for m in matches
        ]

    async def _rerank(
        self,
        query: str,
        matches: list[VectorMatch],
        rerank_top_k: int | None,
    ) -> list[VectorMatch]:
        """Rerank *matches* via the configured ``Reranker``. Empty-``text``
        matches are excluded from the reranker's input (never raises on
        such -- there's no text to rank) and are simply absent from the
        reranked result; original indices are mapped back onto *matches*."""
        rankable_indices = [i for i, m in enumerate(matches) if m.text]
        if not rankable_indices:
            return matches
        rankable_texts = [matches[i].text for i in rankable_indices]
        assert self._reranker is not None  # narrowed by the caller
        ranked = await self._reranker.rerank(query, rankable_texts, top_k=rerank_top_k)
        return [matches[rankable_indices[r.index]] for r in ranked]


class VectorQueryRetriever:
    """Adapts ``RagPipeline`` to ``rag.Retriever`` -- drops into ``RagInputFilter``."""

    def __init__(
        self, pipeline: RagPipeline, *, top_k: int = 5, namespace: str = ""
    ) -> None:
        self._pipeline = pipeline
        self._top_k = top_k
        self._namespace = namespace

    async def retrieve(self, query: str, top_k: int = 5) -> list[Document]:
        """Delegate to ``RagPipeline.aquery`` under this retriever's namespace.

        ``top_k`` here is the ``Retriever`` Protocol's own parameter and
        always wins -- composing callers (e.g. ``RagInputFilter``) pass
        their own configured value explicitly. The ctor's ``top_k`` is
        stored for introspection/parity with the plan's constructor shape
        but is intentionally NOT silently substituted for an explicit
        argument of the same value as the Protocol's default (that would be
        indistinguishable from a caller genuinely wanting 5, and silently
        overriding an explicit call argument is a worse surprise than an
        unused ctor default).
        """
        return await self._pipeline.aquery(
            query, top_k=top_k, namespace=self._namespace
        )


def make_vector_query_tool(
    pipeline: RagPipeline, *, namespace: str = ""
) -> ToolFunction:
    """Factory: build an agent-callable ``vector_query`` tool bound to
    *pipeline* (and *namespace*), returning joined snippets as one string."""

    @tool(
        name="vector_query",
        description="Search indexed documents for content relevant to a query.",
    )
    async def vector_query(query: str, top_k: int = 5) -> str:
        """Search indexed documents for content relevant to the query.

        Args:
            query: The search query.
            top_k: Maximum number of results to return.
        """
        docs = await pipeline.aquery(query, top_k=top_k, namespace=namespace)
        if not docs:
            return ""
        return "\n\n".join(doc.content for doc in docs)

    return vector_query
