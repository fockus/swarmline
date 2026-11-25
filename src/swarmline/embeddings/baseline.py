"""HashEmbedder — dependency-free baseline Embedder (rag-protocols-foundation, Task 2).

Deterministic bag-of-hashed-tokens embedding, no vendor SDK required. Reuses
``skills.bm25._tokenize`` (DRY — same lowercase + non-alnum-split tokenizer
already used for skill discovery) so tokenization stays consistent across
the codebase.

Covers REQ-005..008, 017, 019: fixed dimensionality, deterministic,
L2-normalized (non-empty), zero-vector for empty text, ``count_tokens``
parity, zero external dependencies.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from swarmline.skills.bm25 import _tokenize


def _bucket_sign(token: str, dim: int) -> tuple[int, float]:
    """Hash *token* to an INDEPENDENT ``(bucket, sign)`` pair via blake2b.

    A 16-byte digest is split into two disjoint 8-byte halves: the first
    half picks the bucket (``% dim``), the second half picks the sign. Keeping
    the sign out of the bucket's bit range preserves the signed feature-hashing
    property (colliding tokens partially cancel instead of always reinforcing),
    which would otherwise break whenever ``dim`` is a power of two and the low
    bits fully determine the bucket.
    """
    digest = hashlib.blake2b(token.encode(), digest_size=16).digest()
    bucket = int.from_bytes(digest[:8], "big") % dim
    sign = 1.0 if (digest[8] & 1) else -1.0
    return bucket, sign


def _embed_text(text: str, dim: int) -> list[float]:
    """Pure hashed bag-of-words embedding of *text* into a *dim*-vector."""
    tokens = _tokenize(text)
    vec = [0.0] * dim
    if not tokens:
        return vec

    for token in tokens:
        bucket, sign = _bucket_sign(token, dim)
        vec[bucket] += sign

    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0.0:
        vec = [x / norm for x in vec]
    return vec


class HashEmbedder:
    """Baseline Embedder: hashed bag-of-words, L2-normalized, zero deps.

    Implements the ``Embedder`` Protocol (embed_query/embed_documents/count_tokens).
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string into a fixed-dim, L2-normalized vector."""
        return _embed_text(text, self.dim)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of documents, one vector per input text."""
        return [_embed_text(text, self.dim) for text in texts]

    def count_tokens(self, text: str) -> int:
        """Number of tokens the tokenizer extracts from *text* (0 if empty)."""
        return len(_tokenize(text))
