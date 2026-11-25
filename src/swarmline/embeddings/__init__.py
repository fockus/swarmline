"""Swarmline embeddings — dependency-free baseline Embedder implementations.

Vendor adapters (OpenAI/Cohere/etc.) are deferred to a later spec
(REQ-020); this package exports only the zero-dependency baseline.
"""

from swarmline.embeddings.baseline import HashEmbedder

__all__ = ["HashEmbedder"]
