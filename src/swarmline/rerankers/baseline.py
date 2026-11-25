"""RRFReranker — dependency-free baseline Reranker (rag-protocols-foundation, Task 4).

Reciprocal Rank Fusion (RRF) of two deterministic rankings over the
candidate ``documents``:

1. **Lexical rank** — token-overlap between the query and each document.
   Overlap(doc) = number of query tokens (``skills.bm25._tokenize``) that
   appear in the document's token set. Documents are ordered by
   ``(overlap DESC, input_index ASC)``; ``lex_rank`` is the 1-based
   position in that order.
2. **Positional rank** — the document's original position in the input
   list: ``pos_rank = input_index + 1``.
3. **Fusion** — ``rrf_score = 1/(_RRF_K + lex_rank) + 1/(_RRF_K + pos_rank)``,
   reusing ``skills.hybrid_retriever._RRF_K`` (DRY — same constant used by
   the skill-retrieval hybrid fuser).
4. Results are sorted by ``rrf_score`` descending, with a **stable
   tie-break by original input index** (smaller index first), then
   truncated to ``top_k``.

Covers REQ-014..017: zero external dependencies, deterministic ordering,
stable tie-break, ``top_k`` truncation. An empty query tokenizes to no
tokens, so every document's overlap is 0 and the ranking degrades
gracefully to positional-only order — this never raises.
"""

from __future__ import annotations

from collections.abc import Sequence

from swarmline.protocols.rag import RankedDocument
from swarmline.skills.bm25 import _tokenize
from swarmline.skills.hybrid_retriever import _RRF_K


def _lexical_ranks(query_tokens: list[str], documents: Sequence[str]) -> list[int]:
    """Return the 1-based lexical rank of each document index.

    Ranked by token-overlap-with-query descending, tie-broken by the
    document's original input index ascending.
    """
    doc_sets = [set(_tokenize(doc)) for doc in documents]
    overlaps = [
        sum(1 for tok in query_tokens if tok in doc_set) for doc_set in doc_sets
    ]
    order = sorted(range(len(documents)), key=lambda i: (-overlaps[i], i))
    ranks = [0] * len(documents)
    for rank, idx in enumerate(order, start=1):
        ranks[idx] = rank
    return ranks


class RRFReranker:
    """Baseline Reranker: RRF of lexical overlap and input position, zero deps.

    Implements the ``Reranker`` Protocol (``rerank``).
    """

    async def rerank(
        self, query: str, documents: Sequence[str], *, top_k: int | None = None
    ) -> list[RankedDocument]:
        """Rerank *documents* against *query* via RRF; truncate to *top_k*."""
        if not documents or top_k == 0:
            return []

        query_tokens = _tokenize(query)
        lex_ranks = _lexical_ranks(query_tokens, documents)

        scored = [
            (
                idx,
                1.0 / (_RRF_K + lex_ranks[idx]) + 1.0 / (_RRF_K + idx + 1),
            )
            for idx in range(len(documents))
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))

        ranked = [
            RankedDocument(index=idx, score=score, text=documents[idx])
            for idx, score in scored
        ]
        return ranked[:top_k] if top_k is not None else ranked
