"""TDD tests for Stage C2.2 — ``SemanticRecall`` + ``SemanticRecallInputFilter``.

Uses B2 baselines only (``HashEmbedder`` + ``InMemoryVectorStore``) — zero
vendor installs, matching the plan's "zero vendor installs" requirement.
Covers the 7 plan-mandated tests plus edge cases from the plan's "Edge
cases" section (empty query, re-index overwrite, top_k > stored, export).
"""

from __future__ import annotations

from swarmline.domain_types import Message
from swarmline.embeddings import HashEmbedder
from swarmline.memory import SemanticRecall, SemanticRecallInputFilter
from swarmline.memory.types import MemoryMessage
from swarmline.vectorstores import InMemoryVectorStore

# ---------------------------------------------------------------------------
# Plan-mandated tests (7)
# ---------------------------------------------------------------------------


async def test_semantic_recall_index_then_recall_returns_match() -> None:
    recall = SemanticRecall(HashEmbedder(), InMemoryVectorStore())
    await recall.aindex("apple banana cherry", id="fruit")
    await recall.aindex("rocket engine turbine", id="engineering")
    await recall.aindex("stock market finance report", id="finance")

    matches = await recall.arecall("apple banana", top_k=3)

    assert len(matches) == 3
    assert matches[0].id == "fruit"


async def test_semantic_recall_empty_store_returns_empty() -> None:
    recall = SemanticRecall(HashEmbedder(), InMemoryVectorStore())

    assert await recall.arecall("anything") == []


async def test_semantic_recall_namespace_isolation() -> None:
    store = InMemoryVectorStore()
    embedder = HashEmbedder()
    recall_a = SemanticRecall(embedder, store, namespace="threadA")
    recall_b = SemanticRecall(embedder, store, namespace="threadB")
    await recall_a.aindex("secret plan alpha", id="a1")
    await recall_b.aindex("secret plan beta", id="b1")

    matches_a = await recall_a.arecall("secret plan", top_k=5)

    assert {m.id for m in matches_a} == {"a1"}


async def test_semantic_recall_index_messages_embeds_each() -> None:
    store = InMemoryVectorStore()
    recall = SemanticRecall(HashEmbedder(), store)
    messages = [
        MemoryMessage(role="user", content="first message"),
        MemoryMessage(role="assistant", content="second message"),
        MemoryMessage(role="user", content="third message"),
    ]

    await recall.aindex_messages(messages)

    matches = await recall.arecall("message", top_k=10)
    assert len(matches) == 3


async def test_semantic_recall_near_beats_far() -> None:
    recall = SemanticRecall(HashEmbedder(), InMemoryVectorStore())
    await recall.aindex("the quick brown fox jumps", id="near")
    await recall.aindex("quantum entanglement physics lecture", id="far")

    matches = await recall.arecall("quick brown fox", top_k=2)

    assert matches[0].id == "near"


async def test_semantic_recall_input_filter_injects_recalled_block() -> None:
    store = InMemoryVectorStore()
    recall = SemanticRecall(HashEmbedder(), store)
    await recall.aindex("user likes hiking and camping trips", id="pref1")
    filt = SemanticRecallInputFilter(recall)
    messages = [Message(role="user", content="hiking and camping trips")]

    new_messages, new_prompt = await filt.filter(messages, "You are a helper.")

    assert new_messages == messages
    assert "<recalled_memory>" in new_prompt
    assert "hiking and camping trips" in new_prompt
    assert "You are a helper." in new_prompt


async def test_semantic_recall_input_filter_empty_recall_is_noop() -> None:
    store = InMemoryVectorStore()
    recall = SemanticRecall(HashEmbedder(), store)  # nothing indexed
    filt = SemanticRecallInputFilter(recall)
    messages = [Message(role="user", content="anything")]

    new_messages, new_prompt = await filt.filter(messages, "sys")

    assert new_messages == messages
    assert new_prompt == "sys"


# ---------------------------------------------------------------------------
# Edge cases (plan "Edge cases" section, C2.2)
# ---------------------------------------------------------------------------


async def test_semantic_recall_arecall_empty_query_returns_empty() -> None:
    store = InMemoryVectorStore()
    recall = SemanticRecall(HashEmbedder(), store)
    await recall.aindex("something indexed", id="x")

    assert await recall.arecall("") == []


async def test_semantic_recall_reindexing_same_id_overwrites() -> None:
    store = InMemoryVectorStore()
    recall = SemanticRecall(HashEmbedder(), store)
    await recall.aindex("first version", id="doc")
    await recall.aindex("second version", id="doc")

    matches = await recall.arecall("second version", top_k=10)

    assert len(matches) == 1
    assert matches[0].text == "second version"


async def test_semantic_recall_top_k_larger_than_stored_returns_all() -> None:
    store = InMemoryVectorStore()
    recall = SemanticRecall(HashEmbedder(), store)
    await recall.aindex("one", id="1")
    await recall.aindex("two", id="2")

    matches = await recall.arecall("one two", top_k=100)

    assert len(matches) == 2


async def test_semantic_recall_input_filter_empty_query_is_noop() -> None:
    """Empty last-user-text (no user message at all) -- filter is a no-op
    without ever calling arecall (also covers the zero-vector/empty-query
    edge case at the filter boundary)."""
    store = InMemoryVectorStore()
    recall = SemanticRecall(HashEmbedder(), store)
    await recall.aindex("something", id="x")
    filt = SemanticRecallInputFilter(recall)
    messages = [Message(role="assistant", content="hello")]

    new_messages, new_prompt = await filt.filter(messages, "sys")

    assert new_messages == messages
    assert new_prompt == "sys"


def test_semantic_recall_export_importable() -> None:
    from swarmline.memory import SemanticRecall as ImportedSemanticRecall
    from swarmline.memory import SemanticRecallInputFilter as ImportedFilter

    assert ImportedSemanticRecall is SemanticRecall
    assert ImportedFilter is SemanticRecallInputFilter


# ---------------------------------------------------------------------------
# r1 fix-cycle regressions (asymmetric embedding space, whitespace query,
# namespace default-clobbering)
# ---------------------------------------------------------------------------


class _FakeAsymmetricEmbedder:
    """Distinguishes query vs. document embedding spaces: ``embed_query``
    returns "A-shape" vectors, ``embed_documents`` returns "B-shape"
    vectors -- deterministic per input, but the two spaces never overlap.
    Also counts calls so batching can be asserted."""

    def __init__(self) -> None:
        self.embed_documents_calls = 0

    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, float(len(text))]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embed_documents_calls += 1
        return [[0.0, 1.0, float(len(t))] for t in texts]

    async def count_tokens(self, text: str) -> int:
        return len(text.split())


class _CountingVectorStore(InMemoryVectorStore):
    """InMemoryVectorStore that counts ``upsert`` calls."""

    def __init__(self) -> None:
        super().__init__()
        self.upsert_calls = 0

    async def upsert(self, records, *, namespace: str = "") -> None:  # noqa: ANN001
        self.upsert_calls += 1
        await super().upsert(records, namespace=namespace)


async def test_semantic_recall_aindex_uses_document_side_embedding() -> None:
    """MAJOR 1: aindex must embed via embed_documents (B-shape: [0, 1, len]),
    not embed_query (A-shape: [1, 0, len]) -- a similarity query can't
    discriminate with only one record stored (it always "wins" trivially),
    so inspect the stored record's raw embedding directly."""
    embedder = _FakeAsymmetricEmbedder()
    store = InMemoryVectorStore()
    recall = SemanticRecall(embedder, store)

    await recall.aindex("hello world", id="doc1")

    stored = store._ns[""]["doc1"]
    assert stored.embedding == (0.0, 1.0, 11.0)


async def test_semantic_recall_aindex_messages_batches_single_call() -> None:
    """MAJOR 1: aindex_messages makes exactly ONE embed_documents call and
    ONE store.upsert call for N messages, not N calls of either."""
    embedder = _FakeAsymmetricEmbedder()
    store = _CountingVectorStore()
    recall = SemanticRecall(embedder, store)
    messages = [
        MemoryMessage(role="user", content="first message"),
        MemoryMessage(role="assistant", content="second message"),
        MemoryMessage(role="user", content="third message"),
    ]

    await recall.aindex_messages(messages)

    assert embedder.embed_documents_calls == 1
    assert store.upsert_calls == 1


async def test_semantic_recall_arecall_whitespace_only_returns_empty() -> None:
    """MAJOR 2: a whitespace-only query is treated as empty."""
    store = InMemoryVectorStore()
    recall = SemanticRecall(HashEmbedder(), store)
    await recall.aindex("something indexed", id="x")

    assert await recall.arecall("   ") == []


async def test_semantic_recall_input_filter_whitespace_query_is_noop() -> None:
    """MAJOR 2: whitespace-only last user text -- system_prompt unchanged."""
    store = InMemoryVectorStore()
    recall = SemanticRecall(HashEmbedder(), store)
    await recall.aindex("something", id="x")
    filt = SemanticRecallInputFilter(recall)
    messages = [Message(role="user", content="   ")]

    new_messages, new_prompt = await filt.filter(messages, "sys")

    assert new_messages == messages
    assert new_prompt == "sys"


async def test_semantic_recall_input_filter_default_namespace_uses_ctor_namespace() -> (
    None
):
    """MAJOR 3: a default-namespace filter must not clobber the
    SemanticRecall's own ctor namespace with "" -- it should recall from
    the ctor's namespace ("threadA"), not the "" namespace."""
    store = InMemoryVectorStore()
    embedder = HashEmbedder()
    recall = SemanticRecall(embedder, store, namespace="threadA")
    await recall.aindex("secret plan alpha", id="a1", namespace="threadA")
    await recall.aindex("secret plan beta", id="b1", namespace="")
    filt = SemanticRecallInputFilter(recall)
    messages = [Message(role="user", content="secret plan")]

    _, new_prompt = await filt.filter(messages, "sys")

    assert "secret plan alpha" in new_prompt
    assert "secret plan beta" not in new_prompt


async def test_semantic_recall_aindex_empty_text_is_skipped() -> None:
    """r2 minor: empty text embeds to a zero vector and pollutes recall."""
    recall = SemanticRecall(HashEmbedder(dim=16), InMemoryVectorStore())

    await recall.aindex("   ")
    await recall.aindex("real content")

    matches = await recall.arecall("real content", top_k=10)
    assert [m.text for m in matches] == ["real content"]


async def test_semantic_recall_index_messages_skips_empty_content() -> None:
    recall = SemanticRecall(HashEmbedder(dim=16), InMemoryVectorStore())

    await recall.aindex_messages(
        [
            MemoryMessage(role="user", content=""),
            MemoryMessage(role="user", content="keep me"),
        ]
    )

    matches = await recall.arecall("keep me", top_k=10)
    assert [m.text for m in matches] == ["keep me"]


async def test_semantic_recall_input_filter_drops_empty_text_matches() -> None:
    """A pre-existing store with an empty-text record must not render an
    empty <recalled_memory> block."""
    from swarmline.protocols.rag import VectorRecord

    embedder = HashEmbedder(dim=16)
    store = InMemoryVectorStore()
    empty_vec = await embedder.embed_documents([""])
    await store.upsert(
        [VectorRecord(id="legacy", embedding=empty_vec[0], text="", metadata={})],
        namespace="",
    )
    recall = SemanticRecall(embedder, store)
    fltr = SemanticRecallInputFilter(recall)

    messages = [Message(role="user", content="anything")]
    out_messages, out_prompt = await fltr.filter(messages, "base prompt")

    assert out_messages == messages
    assert out_prompt == "base prompt"
