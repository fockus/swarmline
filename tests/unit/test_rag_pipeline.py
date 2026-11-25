"""TDD tests for Stage C2.4 — ``chunk_text`` + ``RagPipeline`` +
``VectorQueryRetriever`` + ``make_vector_query_tool``.

B2 baselines only (``HashEmbedder`` + ``InMemoryVectorStore`` +
``RRFReranker``) -- zero vendor installs. ``swarmline.rag`` stays untouched
(Strangler-Fig, C-DP5): this module is a sibling, reusing ``rag.Document``
and satisfying ``rag.Retriever`` so results drop into the existing
``RagInputFilter``. Covers the 8 plan-mandated tests plus the plan's
"Edge cases" (overlap clamp, empty aindex, reranker truncation below
top_k, empty-text matches skipped from rerank).
"""

from __future__ import annotations

from swarmline.embeddings import HashEmbedder
from swarmline.rag import Document, RagInputFilter, Retriever
from swarmline.rag_pipeline import (
    RagPipeline,
    VectorQueryRetriever,
    chunk_text,
    make_vector_query_tool,
)
from swarmline.rerankers import RRFReranker
from swarmline.vectorstores import InMemoryVectorStore

# ---------------------------------------------------------------------------
# Plan-mandated tests (8)
# ---------------------------------------------------------------------------


def test_chunk_text_splits_with_overlap() -> None:
    long_text = "".join(f"word{i} " for i in range(500))  # ~3500 chars

    chunks = chunk_text(long_text, max_chars=200, overlap=50)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 200
    # Consecutive full-size chunks share exactly `overlap` chars: chunk[i]'s
    # tail == chunk[i+1]'s head (the final, possibly-shorter chunk is excluded).
    for i in range(len(chunks) - 1):
        if len(chunks[i]) == 200:
            assert chunks[i][-50:] == chunks[i + 1][:50]

    short_text = "just one short chunk"
    assert chunk_text(short_text, max_chars=200, overlap=50) == [short_text]


async def test_rag_pipeline_index_returns_chunk_count() -> None:
    pipeline = RagPipeline(HashEmbedder(), InMemoryVectorStore())
    long_text = "".join(f"word{i} " for i in range(500))

    count = await pipeline.aindex([long_text])

    assert count > 1


async def test_rag_pipeline_query_returns_documents_nearest_first() -> None:
    pipeline = RagPipeline(HashEmbedder(), InMemoryVectorStore())
    await pipeline.aindex(
        ["the quick brown fox jumps", "quantum entanglement physics lecture"]
    )

    docs = await pipeline.aquery("quick brown fox", top_k=2)

    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)
    assert docs[0].score is not None
    assert docs[0].score >= docs[1].score


async def test_rag_pipeline_query_empty_store_returns_empty() -> None:
    pipeline = RagPipeline(HashEmbedder(), InMemoryVectorStore())

    docs = await pipeline.aquery("anything")

    assert docs == []


async def test_rag_pipeline_with_reranker_reorders() -> None:
    """The reranked order must actually DIFFER from the no-reranker
    baseline (r1 minor: a permutation-of-same-set assert can't catch a
    reranker whose result is silently ignored). A deterministic reversing
    reranker makes the expected order exact."""
    from swarmline.protocols.rag import RankedDocument

    class _ReversingReranker:
        async def rerank(self, query, documents, *, top_k=None):  # noqa: ANN001
            order = list(reversed(range(len(documents))))[: top_k or len(documents)]
            return [
                RankedDocument(index=i, score=1.0 - n * 0.1, text=documents[i])
                for n, i in enumerate(order)
            ]

    store = InMemoryVectorStore()
    embedder = HashEmbedder()
    plain = RagPipeline(embedder, store)
    await plain.aindex(["alpha beta gamma", "delta epsilon zeta", "eta theta iota"])
    baseline = [d.content for d in await plain.aquery("alpha beta gamma", top_k=3)]

    reranked_pipeline = RagPipeline(embedder, store, reranker=_ReversingReranker())
    reranked = [
        d.content for d in await reranked_pipeline.aquery("alpha beta gamma", top_k=3)
    ]

    assert reranked == list(reversed(baseline))
    assert reranked != baseline


async def test_vector_query_retriever_is_retriever() -> None:
    store = InMemoryVectorStore()
    embedder = HashEmbedder()
    pipeline = RagPipeline(embedder, store)
    await pipeline.aindex(["user likes hiking and camping trips"])
    retriever = VectorQueryRetriever(pipeline)

    assert isinstance(retriever, Retriever)

    filt = RagInputFilter(retriever)
    messages = [_msg("hiking and camping trips")]
    _, new_prompt = await filt.filter(messages, "You are a helper.")

    assert "<context>" in new_prompt
    assert "hiking and camping trips" in new_prompt


async def test_vector_query_tool_returns_snippets() -> None:
    pipeline = RagPipeline(HashEmbedder(), InMemoryVectorStore())
    await pipeline.aindex(["deposits earn interest over time"])
    tool_fn = make_vector_query_tool(pipeline)

    result = await tool_fn(query="deposits earn interest", top_k=3)

    assert "deposits earn interest over time" in result


async def test_rag_pipeline_namespace_isolation() -> None:
    store = InMemoryVectorStore()
    embedder = HashEmbedder()
    pipeline_a = RagPipeline(embedder, store, namespace="threadA")
    pipeline_b = RagPipeline(embedder, store, namespace="threadB")
    await pipeline_a.aindex(["secret plan alpha"])
    await pipeline_b.aindex(["secret plan beta"])

    docs_a = await pipeline_a.aquery("secret plan", top_k=5)

    assert {d.content for d in docs_a} == {"secret plan alpha"}


# ---------------------------------------------------------------------------
# Edge cases (plan "Edge cases" section, C2.4)
# ---------------------------------------------------------------------------


def test_chunk_text_overlap_clamped_when_overlap_exceeds_max_chars() -> None:
    """overlap >= max_chars must clamp to max_chars - 1 -- avoids an
    infinite loop (step would otherwise be 0 or negative)."""
    long_text = "x" * 500

    chunks = chunk_text(long_text, max_chars=10, overlap=10)  # overlap == max_chars

    assert len(chunks) > 1
    assert all(len(c) <= 10 for c in chunks)

    chunks2 = chunk_text(long_text, max_chars=10, overlap=999)  # overlap > max_chars
    assert len(chunks2) > 1
    assert all(len(c) <= 10 for c in chunks2)


class _FakeAsymmetricEmbedder:
    """Distinguishes query vs. document embedding spaces (C2.2 lesson):
    ``embed_query`` returns "A-shape" vectors, ``embed_documents`` returns
    "B-shape" vectors -- deterministic per input, never overlapping.
    ``HashEmbedder`` alone can't catch a wrong-side regression since both
    its sides are identical."""

    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, float(len(text))]

    async def embed_documents(self, texts) -> list[list[float]]:  # noqa: ANN001
        return [[0.0, 1.0, float(len(t))] for t in texts]

    def count_tokens(self, text: str) -> int:
        return len(text.split())


async def test_rag_pipeline_aindex_uses_document_side_embedding() -> None:
    """aindex must embed chunks via embed_documents (B-shape), not
    embed_query (A-shape) -- inspect the stored record's vector directly
    (a similarity query can't discriminate reliably with one record)."""
    store = InMemoryVectorStore()
    pipeline = RagPipeline(_FakeAsymmetricEmbedder(), store, chunker=lambda t: [t])

    await pipeline.aindex(["hello world"])

    records = list(store._ns[""].values())
    assert len(records) == 1
    assert records[0].embedding == (0.0, 1.0, 11.0)


async def test_rag_pipeline_aindex_empty_returns_zero_no_upsert() -> None:
    class _CountingStore(InMemoryVectorStore):
        def __init__(self) -> None:
            super().__init__()
            self.upsert_calls = 0

        async def upsert(self, records, *, namespace: str = "") -> None:  # noqa: ANN001
            self.upsert_calls += 1
            await super().upsert(records, namespace=namespace)

    store = _CountingStore()
    pipeline = RagPipeline(HashEmbedder(), store)

    assert await pipeline.aindex([]) == 0
    assert await pipeline.aindex([""]) == 0
    assert store.upsert_calls == 0


async def test_rag_pipeline_reranker_truncates_below_top_k() -> None:
    store = InMemoryVectorStore()
    embedder = HashEmbedder()
    pipeline = RagPipeline(embedder, store, reranker=RRFReranker())
    await pipeline.aindex(["alpha one", "beta two", "gamma three", "delta four"])

    docs = await pipeline.aquery("alpha beta gamma delta", top_k=4, rerank_top_k=2)

    assert len(docs) == 2


async def test_rag_pipeline_rerank_skips_empty_text_matches() -> None:
    """A VectorMatch with empty text must never reach the Reranker (which
    would have nothing to rank), must never raise, and -- since the blank
    entry sits in the MIDDLE of the results -- every subsequent real
    match's reranked index must still map back correctly (not just line up
    1:1 by accident, as it would if there were only a trailing blank)."""

    class _RaisesOnEmptyTextReranker(RRFReranker):
        async def rerank(self, query: str, documents, *, top_k=None):  # noqa: ANN001
            assert all(d for d in documents), "empty text leaked into rerank input"
            return await super().rerank(query, documents, top_k=top_k)

    class _EmptyTextInMiddleStore(InMemoryVectorStore):
        async def query(self, embedding, *, top_k=5, namespace="", filter=None):  # noqa: ANN001
            matches = await super().query(
                embedding, top_k=top_k, namespace=namespace, filter=filter
            )
            from swarmline.protocols.rag import VectorMatch

            if len(matches) < 2:
                return matches
            blank = VectorMatch(id="blank", score=0.0, text="")
            return [matches[0], blank, *matches[1:]]

    store = _EmptyTextInMiddleStore()
    embedder = HashEmbedder()
    pipeline = RagPipeline(embedder, store, reranker=_RaisesOnEmptyTextReranker())
    await pipeline.aindex(["alpha one", "beta two", "gamma three"])

    docs = await pipeline.aquery("alpha beta gamma", top_k=5)

    assert {d.content for d in docs} == {"alpha one", "beta two", "gamma three"}


def _msg(content: str):  # noqa: ANN202
    from swarmline.runtime.types import Message

    return Message(role="user", content=content)


async def test_rag_pipeline_aquery_whitespace_query_returns_empty() -> None:
    """r1 minor: a zero-vector query would surface arbitrary records at
    score ~0 (C2.2 lesson) — whitespace-only query short-circuits to []."""
    pipeline = RagPipeline(HashEmbedder(), InMemoryVectorStore())
    await pipeline.aindex(["real content here"])

    assert await pipeline.aquery("   ", top_k=5) == []

    tool_fn = make_vector_query_tool(pipeline)
    result = await tool_fn(query="   ", top_k=5)
    assert "real content here" not in result


async def test_rag_pipeline_aindex_whitespace_only_doc_indexes_nothing() -> None:
    """r1 minor: whitespace-only document must produce 0 chunks / no upsert
    (blank zero-vector records pollute retrieval)."""
    store = InMemoryVectorStore()
    pipeline = RagPipeline(HashEmbedder(), store)

    assert chunk_text("   \n\t  ") == []
    assert await pipeline.aindex(["   \n\t  "]) == 0
    assert await pipeline.aquery("anything", top_k=5) == []
