"""RAG / Retriever Protocol — document retrieval and context injection.

Provides:
- Document: frozen dataclass for retrieved documents
- Retriever: runtime-checkable protocol for retrieval backends
- SimpleRetriever: builtin in-memory retriever using word overlap scoring
- RagInputFilter: InputFilter that injects retrieved context into system_prompt
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from swarmline.runtime.types import Message


@dataclass(frozen=True)
class Document:
    """A retrieved document with content, metadata, and optional relevance score."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float | None = None


@runtime_checkable
class Retriever(Protocol):
    """Protocol for document retrieval backends.

    Implementations must provide an async retrieve method that returns
    documents ranked by relevance to the query.
    """

    async def retrieve(self, query: str, top_k: int = 5) -> list[Document]:
        """Retrieve top_k documents relevant to query."""
        ...


class SimpleRetriever:
    """In-memory retriever using word overlap scoring.

    Intended for development and testing. Uses simple word overlap
    (intersection of word counters) as a proxy for TF-IDF relevance.

    Args:
        documents: List of documents to search over.
    """

    def __init__(self, documents: list[Document]) -> None:
        self._documents = documents

    async def retrieve(self, query: str, top_k: int = 5) -> list[Document]:
        """Retrieve documents ranked by word overlap with query.

        Returns empty list if query is empty or no documents match.
        """
        if not query.strip():
            return []

        query_words = Counter(query.lower().split())

        scored: list[Document] = []
        for doc in self._documents:
            doc_words = Counter(doc.content.lower().split())
            # Sum of minimum counts for overlapping words
            overlap = sum(
                min(query_words[w], doc_words[w])
                for w in query_words
                if w in doc_words
            )
            if overlap > 0:
                scored.append(
                    Document(
                        content=doc.content,
                        metadata=doc.metadata,
                        score=float(overlap),
                    )
                )

        scored.sort(key=lambda d: d.score or 0.0, reverse=True)
        return scored[:top_k]


class TieredRetriever:
    """Retriever backed by TieredContextManager.

    Searches L0 abstracts for keyword matches, returns L1 overviews
    as Documents. Drop-in replacement for SimpleRetriever.

    Args:
        tiered_manager: A TieredContextManager instance (or any object
            with an async ``search(query, budget_tokens, top_k)`` method).
    """

    def __init__(self, tiered_manager: Any, top_k: int = 5) -> None:
        from swarmline.memory_bank.tiered import TieredContextManager

        if not isinstance(tiered_manager, TieredContextManager):
            raise TypeError(
                f"Expected TieredContextManager, got {type(tiered_manager).__name__}"
            )
        self._manager: TieredContextManager = tiered_manager
        self._top_k = top_k

    async def retrieve(self, query: str, top_k: int = 5) -> list[Document]:
        """Retrieve documents from memory bank via tiered search."""
        entries = await self._manager.search(
            query, budget_tokens=top_k * 2000, top_k=top_k
        )
        return [
            Document(
                content=entry.content,
                metadata={"path": entry.path, "tier": entry.tier},
            )
            for entry in entries
        ]


class RagInputFilter:
    """InputFilter that injects retrieved documents into system_prompt.

    Extracts the query from the last user message, retrieves relevant
    documents via the configured Retriever, and prepends them to the
    system prompt wrapped in <context>...</context> tags.

    Args:
        retriever: A Retriever implementation.
        top_k: Maximum number of documents to retrieve per query.
    """

    def __init__(self, retriever: Retriever, top_k: int = 5) -> None:
        self._retriever = retriever
        self._top_k = top_k

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        """Retrieve documents and inject them into system_prompt.

        Returns (messages, enriched_system_prompt). Messages are never modified.
        """
        query = self._extract_last_user_text(messages)
        if not query:
            return messages, system_prompt

        docs = await self._retriever.retrieve(query, self._top_k)
        if not docs:
            return messages, system_prompt

        context_block = self._format_context(docs)
        enriched = f"{context_block}\n{system_prompt}" if system_prompt else context_block
        return messages, enriched

    @staticmethod
    def _extract_last_user_text(messages: list[Message]) -> str:
        """Extract text from the last user message."""
        for msg in reversed(messages):
            if msg.role == "user" and msg.content:
                return msg.content
        return ""

    @staticmethod
    def _format_context(docs: list[Document]) -> str:
        """Format documents as a <context> block."""
        lines = [doc.content for doc in docs]
        inner = "\n".join(lines)
        return f"<context>\n{inner}\n</context>"
