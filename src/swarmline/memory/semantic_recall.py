"""``SemanticRecall`` + ``SemanticRecallInputFilter`` — B2 semantic recall
over messages/episodic memory (Stage C2.2, Mastra parity).

Thread/resource-scoped semantic memory: index arbitrary text (or message
history) into a B2 ``VectorStore`` via a B2 ``Embedder``, then recall the
most similar entries for a query later. ``namespace`` is how thread-scope
(e.g. ``str(SessionKey)``) or resource-scope (``user_id``) isolation is
achieved -- ``InMemoryVectorStore`` already isolates by namespace (B2.4);
this class adds no isolation logic of its own.

Zero vendor installs required for the offline test suite: ``HashEmbedder`` +
``InMemoryVectorStore`` (B2 baselines) are sufficient.

``SemanticRecallInputFilter`` mirrors ``swarmline.rag.RagInputFilter``:
injects a ``<recalled_memory>`` block into ``system_prompt`` only; messages
are never modified; an empty query or empty recall is a strict no-op.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from swarmline.domain_types import Message
from swarmline.memory.types import MemoryMessage

if TYPE_CHECKING:
    # Deferred for the same reason as memory/working.py: `swarmline.protocols`
    # package init pulls in `protocols.memory`, which imports from
    # `swarmline.memory.types` -- an eager import from `swarmline.protocols`
    # here (this module is eagerly re-exported via `swarmline.memory.__init__`)
    # risks a circular import. `protocols.rag` itself has zero further
    # swarmline dependencies, so a lazy, function-local import (see `aindex`)
    # is safe whenever a runtime value (not just a type) is actually needed.
    from swarmline.protocols.rag import Embedder, VectorMatch, VectorStore


class SemanticRecall:
    """Index + recall over a B2 Embedder/VectorStore pair.

    ISP: constructor + 3 methods (``aindex``/``aindex_messages``/``arecall``).
    """

    def __init__(
        self, embedder: Embedder, store: VectorStore, *, namespace: str = ""
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._namespace = namespace

    async def aindex(
        self,
        text: str,
        *,
        id: str | None = None,  # noqa: A002 -- matches the plan's real signature
        metadata: Mapping[str, Any] | None = None,
        namespace: str | None = None,
    ) -> None:
        """Embed ``text`` on the DOCUMENT side (``embed_documents``, NOT
        ``embed_query``) and upsert it as one record (idempotent by id --
        re-indexing the same id overwrites, reusing B2.4 upsert semantics).

        Asymmetric vendor embedders keep query/document vectors in distinct
        spaces (e.g. instruction-prefixed queries); indexed content must use
        the document side so it is comparable against a query-side vector at
        recall time. ``HashEmbedder`` happens to make both sides identical,
        which would silently mask using the wrong one here.
        """
        from swarmline.protocols.rag import VectorRecord

        if not text.strip():
            return  # empty text embeds to a zero vector and pollutes recall
        ns = self._namespace if namespace is None else namespace
        (vector,) = await self._embedder.embed_documents([text])
        record = VectorRecord(
            id=id or uuid4().hex,
            embedding=vector,
            text=text,
            metadata=dict(metadata or {}),
        )
        await self._store.upsert([record], namespace=ns)

    async def aindex_messages(
        self, messages: Sequence[MemoryMessage], *, namespace: str | None = None
    ) -> None:
        """Batch-index all messages: ONE ``embed_documents`` call for every
        message's content, then ONE ``store.upsert`` call for all resulting
        records (not a per-message ``aindex`` loop)."""
        from swarmline.protocols.rag import VectorRecord

        texts = [m.content for m in messages if m.content and m.content.strip()]
        if not texts:
            return
        ns = self._namespace if namespace is None else namespace
        vectors = await self._embedder.embed_documents(texts)
        records = [
            VectorRecord(id=uuid4().hex, embedding=vector, text=text, metadata={})
            for text, vector in zip(texts, vectors, strict=True)
        ]
        await self._store.upsert(records, namespace=ns)

    async def arecall(
        self, query: str, *, top_k: int = 5, namespace: str | None = None
    ) -> list[VectorMatch]:
        """Return the top-``top_k`` most similar indexed entries for ``query``.

        ``query`` is stripped first -- a whitespace-only query is treated as
        empty and short-circuits to ``[]`` without touching the
        embedder/store (otherwise it would embed to a near-zero vector and
        the store would return unrelated records at score ~0.0). A
        zero-norm embedding (HashEmbedder's empty-text edge) is tolerated
        downstream regardless -- ``InMemoryVectorStore``'s cosine similarity
        never divides by zero. ``top_k`` larger than the stored count simply
        returns everything (no error). Recall uses ``embed_query`` (the
        query side of the embedding space; see ``aindex`` for the document
        side).
        """
        query = query.strip()
        if not query:
            return []
        ns = self._namespace if namespace is None else namespace
        vector = await self._embedder.embed_query(query)
        return await self._store.query(vector, top_k=top_k, namespace=ns)


class SemanticRecallInputFilter:
    """InputFilter that injects recalled memory into ``system_prompt``.

    Mirrors ``swarmline.rag.RagInputFilter``: extract the last user
    message's text, recall via ``SemanticRecall``, wrap matches in
    ``<recalled_memory>...</recalled_memory>``. Messages are never
    modified; an empty query or empty recall is a strict no-op (no empty
    block is ever injected).
    """

    def __init__(
        self, recall: SemanticRecall, *, top_k: int = 5, namespace: str | None = None
    ) -> None:
        self._recall = recall
        self._top_k = top_k
        # None (not "") -- so a default filter falls through to the
        # SemanticRecall's own ctor namespace instead of clobbering it with
        # "" (see SemanticRecall.arecall's `None`-means-"use ctor" fallback).
        self._namespace = namespace

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        """Return ``(messages, enriched_system_prompt)``; messages untouched."""
        query = self._extract_last_user_text(messages).strip()
        if not query:
            return messages, system_prompt

        matches = await self._recall.arecall(
            query, top_k=self._top_k, namespace=self._namespace
        )
        # Drop empty-text records (pre-existing stores may hold them) so a
        # non-empty match list can never render an empty recalled block.
        matches = [m for m in matches if m.text and m.text.strip()]
        if not matches:
            return messages, system_prompt

        block = self._format_block(matches)
        enriched = f"{block}\n{system_prompt}" if system_prompt else block
        return messages, enriched

    @staticmethod
    def _extract_last_user_text(messages: list[Message]) -> str:
        for msg in reversed(messages):
            if msg.role == "user" and msg.content:
                return msg.content
        return ""

    @staticmethod
    def _format_block(matches: list[VectorMatch]) -> str:
        inner = "\n".join(match.text for match in matches)
        return f"<recalled_memory>\n{inner}\n</recalled_memory>"
