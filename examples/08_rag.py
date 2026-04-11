"""RAG -- retrieval-augmented generation with context injection.

Demonstrates: Document, SimpleRetriever, RagInputFilter.
No API keys required.
"""

import asyncio

from swarmline.rag import Document, RagInputFilter, SimpleRetriever
from swarmline.runtime.types import Message


async def main() -> None:
    # 1. Create a document corpus
    docs = [
        Document(content="Python is a programming language created by Guido van Rossum.", metadata={"source": "wiki"}),
        Document(content="Rust is a systems programming language focused on safety.", metadata={"source": "wiki"}),
        Document(content="Swarmline is an LLM-agnostic framework for building AI agents.", metadata={"source": "docs"}),
        Document(content="The weather in Berlin is often cloudy in winter.", metadata={"source": "travel"}),
    ]

    # 2. Create retriever and search
    retriever = SimpleRetriever(documents=docs)
    results = await retriever.retrieve("programming language", top_k=2)
    print("Retrieved documents:")
    for doc in results:
        print(f"  score={doc.score or 0.0:.1f}: {doc.content[:60]}...")

    # 3. RagInputFilter -- auto-inject context into system prompt
    rag_filter = RagInputFilter(retriever=retriever, top_k=2)
    messages = [Message(role="user", content="Tell me about programming languages")]
    filtered_msgs, enriched_prompt = await rag_filter.filter(messages, "You are a helpful assistant.")

    print(f"\nEnriched system prompt:\n{enriched_prompt}")


if __name__ == "__main__":
    asyncio.run(main())
