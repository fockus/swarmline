"""Swarmline rerankers — dependency-free baseline Reranker implementations.

Vendor adapters (Cohere/CrossEncoder/Voyage/etc.) are deferred to a later
spec (REQ-020); this package exports only the zero-dependency baseline.
"""

from swarmline.rerankers.baseline import RRFReranker

__all__ = ["RRFReranker"]
