"""Unit tests for RAG / Retriever Protocol (IDEA-028).

Tests cover:
- Document dataclass: creation, fields, frozen
- Retriever protocol compliance (SimpleRetriever)
- SimpleRetriever: retrieve returns sorted results
- SimpleRetriever: top_k limits results
- SimpleRetriever: empty query returns empty
- RagInputFilter: injects context into system_prompt
- RagInputFilter: preserves messages unchanged
- RuntimeConfig accepts retriever field
"""

from __future__ import annotations

import dataclasses

import pytest

from swarmline.rag import Document, RagInputFilter, Retriever, SimpleRetriever
from swarmline.runtime.types import Message, RuntimeConfig


# ---------------------------------------------------------------------------
# Document dataclass
# ---------------------------------------------------------------------------


class TestDocument:
    def test_create_with_defaults(self) -> None:
        doc = Document(content="hello world")
        assert doc.content == "hello world"
        assert doc.metadata == {}
        assert doc.score is None

    def test_create_with_all_fields(self) -> None:
        doc = Document(content="text", metadata={"src": "wiki"}, score=0.95)
        assert doc.content == "text"
        assert doc.metadata == {"src": "wiki"}
        assert doc.score == 0.95

    def test_frozen_immutable(self) -> None:
        doc = Document(content="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            doc.content = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Retriever protocol compliance
# ---------------------------------------------------------------------------


class TestRetrieverProtocol:
    def test_simple_retriever_is_runtime_checkable(self) -> None:
        retriever = SimpleRetriever(documents=[])
        assert isinstance(retriever, Retriever)


# ---------------------------------------------------------------------------
# SimpleRetriever
# ---------------------------------------------------------------------------


class TestSimpleRetriever:
    @pytest.fixture()
    def docs(self) -> list[Document]:
        return [
            Document(content="Python is a programming language"),
            Document(content="Java is also a programming language"),
            Document(content="The weather is sunny today"),
            Document(content="Python has great libraries for data science"),
        ]

    async def test_retrieve_returns_sorted_by_score(self, docs: list[Document]) -> None:
        retriever = SimpleRetriever(documents=docs)
        results = await retriever.retrieve("Python programming", top_k=10)
        assert len(results) > 0
        # First result should be most relevant to "Python programming"
        assert "Python" in results[0].content
        # Scores should be descending
        scores = [r.score for r in results if r.score is not None]
        assert scores == sorted(scores, reverse=True)

    async def test_retrieve_top_k_limits_results(self, docs: list[Document]) -> None:
        retriever = SimpleRetriever(documents=docs)
        results = await retriever.retrieve("programming language", top_k=2)
        assert len(results) == 2

    async def test_retrieve_empty_query_returns_empty(
        self, docs: list[Document]
    ) -> None:
        retriever = SimpleRetriever(documents=docs)
        results = await retriever.retrieve("", top_k=5)
        assert results == []

    async def test_retrieve_no_match_returns_empty(self) -> None:
        docs = [Document(content="alpha beta gamma")]
        retriever = SimpleRetriever(documents=docs)
        results = await retriever.retrieve("zzzznotfound", top_k=5)
        assert results == []

    async def test_retrieve_preserves_metadata(self) -> None:
        docs = [Document(content="hello world", metadata={"source": "test"})]
        retriever = SimpleRetriever(documents=docs)
        results = await retriever.retrieve("hello", top_k=5)
        assert len(results) == 1
        assert results[0].metadata == {"source": "test"}


# ---------------------------------------------------------------------------
# RagInputFilter
# ---------------------------------------------------------------------------


class TestRagInputFilter:
    async def test_injects_context_into_system_prompt(self) -> None:
        docs = [
            Document(content="Relevant fact A"),
            Document(content="Relevant fact B"),
        ]
        retriever = SimpleRetriever(documents=docs)
        rag_filter = RagInputFilter(retriever=retriever, top_k=5)

        messages = [Message(role="user", content="Tell me about fact A")]
        _, enriched_prompt = await rag_filter.filter(messages, "You are helpful.")

        assert "<context>" in enriched_prompt
        assert "</context>" in enriched_prompt
        assert "Relevant fact A" in enriched_prompt
        assert "You are helpful." in enriched_prompt

    async def test_preserves_messages_unchanged(self) -> None:
        docs = [Document(content="some doc")]
        retriever = SimpleRetriever(documents=docs)
        rag_filter = RagInputFilter(retriever=retriever, top_k=5)

        messages = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
            Message(role="user", content="some"),
        ]
        result_messages, _ = await rag_filter.filter(messages, "sys")
        assert result_messages is messages  # same object, not modified

    async def test_uses_last_user_message_as_query(self) -> None:
        docs = [
            Document(content="cats are fluffy"),
            Document(content="dogs are loyal"),
        ]
        retriever = SimpleRetriever(documents=docs)
        rag_filter = RagInputFilter(retriever=retriever, top_k=5)

        messages = [
            Message(role="user", content="tell me about dogs"),
            Message(role="assistant", content="sure"),
            Message(role="user", content="cats"),
        ]
        _, enriched = await rag_filter.filter(messages, "")
        # Last user message is "cats", so cats doc should be in context
        assert "cats are fluffy" in enriched

    async def test_no_user_message_returns_unchanged(self) -> None:
        retriever = SimpleRetriever(documents=[Document(content="x")])
        rag_filter = RagInputFilter(retriever=retriever, top_k=5)

        messages = [Message(role="assistant", content="hi")]
        result_msgs, result_prompt = await rag_filter.filter(messages, "original")
        assert result_prompt == "original"

    async def test_is_input_filter_compliant(self) -> None:
        from swarmline.input_filters import InputFilter

        retriever = SimpleRetriever(documents=[])
        rag_filter = RagInputFilter(retriever=retriever)
        assert isinstance(rag_filter, InputFilter)


# ---------------------------------------------------------------------------
# RuntimeConfig.retriever field
# ---------------------------------------------------------------------------


class TestRuntimeConfigRetriever:
    def test_runtime_config_accepts_retriever_field(self) -> None:
        retriever = SimpleRetriever(documents=[])
        config = RuntimeConfig(runtime_name="thin", retriever=retriever)
        assert config.retriever is retriever

    def test_runtime_config_retriever_defaults_to_none(self) -> None:
        config = RuntimeConfig(runtime_name="thin")
        assert config.retriever is None
