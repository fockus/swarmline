# RAG (Retrieval-Augmented Generation)

Inject relevant documents into the system prompt before each LLM call. Swarmline's RAG integrates via the `InputFilter` protocol — no special runtime changes needed.

## Quick Start

```python
from swarmline.rag import Document, SimpleRetriever
from swarmline.runtime.types import RuntimeConfig

docs = [
    Document(content="Paris is the capital of France.", metadata={"source": "geo"}),
    Document(content="Python was created by Guido van Rossum.", metadata={"source": "tech"}),
    Document(content="The Eiffel Tower is 330 meters tall.", metadata={"source": "geo"}),
]

retriever = SimpleRetriever(documents=docs)

config = RuntimeConfig(
    runtime_name="thin",
    retriever=retriever,  # auto-wraps into RagInputFilter
)
```

When `retriever` is set in `RuntimeConfig`, ThinRuntime automatically creates a `RagInputFilter` and prepends it to the input filter chain.

## How It Works

```
User message: "What is the capital of France?"
    │
    ▼
RagInputFilter extracts query from last user message
    │
    ▼
Retriever.retrieve(query, top_k=5)
    │
    ▼
Returns: [Document(content="Paris is the capital of France.", score=0.8)]
    │
    ▼
Injects into system prompt:
    <context>
    Paris is the capital of France.
    </context>
    {original system prompt}
    │
    ▼
LLM receives enriched context
```

## Retriever Protocol

Any class with a `retrieve` method works:

```python
class Retriever(Protocol):
    async def retrieve(self, query: str, top_k: int = 5) -> list[Document]: ...
```

### Document

```python
@dataclass(frozen=True)
class Document:
    content: str                        # the text content
    metadata: dict[str, Any] = field(default_factory=dict)  # arbitrary metadata
    score: float | None = None          # relevance score (set by retriever)
```

## Built-in: SimpleRetriever

A word-overlap retriever for development and testing. Not suitable for production — use a vector database instead.

```python
from swarmline.rag import SimpleRetriever, Document

retriever = SimpleRetriever(documents=[
    Document(content="Django is a Python web framework."),
    Document(content="FastAPI uses async/await for performance."),
])

results = await retriever.retrieve("python web framework", top_k=2)
# [Document(content="Django is a Python web framework.", score=3.0), ...]
```

Algorithm: lowercase word overlap counting. No TF-IDF, no embeddings.

## Custom Retrievers

### Vector Database (Pinecone)

```python
class PineconeRetriever:
    def __init__(self, index, embedder):
        self._index = index
        self._embedder = embedder

    async def retrieve(self, query: str, top_k: int = 5) -> list[Document]:
        embedding = await self._embedder.embed(query)
        results = self._index.query(vector=embedding, top_k=top_k)
        return [
            Document(
                content=r.metadata["text"],
                metadata=r.metadata,
                score=r.score,
            )
            for r in results.matches
        ]
```

### Hybrid Search

```python
class HybridRetriever:
    def __init__(self, vector_retriever, keyword_retriever):
        self._vector = vector_retriever
        self._keyword = keyword_retriever

    async def retrieve(self, query: str, top_k: int = 5) -> list[Document]:
        vector_results = await self._vector.retrieve(query, top_k)
        keyword_results = await self._keyword.retrieve(query, top_k)
        return merge_and_deduplicate(vector_results, keyword_results, top_k)
```

## Explicit RagInputFilter

For more control, create `RagInputFilter` manually:

```python
from swarmline.rag import RagInputFilter, SimpleRetriever

retriever = SimpleRetriever(documents=docs)
rag_filter = RagInputFilter(retriever=retriever, top_k=3)

config = RuntimeConfig(
    runtime_name="thin",
    input_filters=[rag_filter],  # manual placement in filter chain
)
```

This gives you control over filter ordering. When using `RuntimeConfig.retriever`, the auto-created `RagInputFilter` is always prepended first.

## Combining with Input Filters

RAG works alongside other input filters:

```python
from swarmline.input_filters import MaxTokensFilter, SystemPromptInjector

config = RuntimeConfig(
    runtime_name="thin",
    retriever=retriever,  # auto-prepends RagInputFilter
    input_filters=[
        SystemPromptInjector(extra_text="Reply in English.", position="prepend"),
        MaxTokensFilter(max_tokens=64_000),
    ],
)
# Effective chain: RagInputFilter → SystemPromptInjector → MaxTokensFilter
```
