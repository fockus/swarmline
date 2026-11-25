"""Swarmline vectorstores — dependency-free baseline VectorStore implementations.

Vendor adapters (pgvector/Qdrant/Chroma/Pinecone/sqlite-vec/etc.) are
deferred to a later spec (REQ-020); this package exports only the
zero-dependency baseline.
"""

from swarmline.vectorstores.baseline import InMemoryVectorStore

__all__ = ["InMemoryVectorStore"]
