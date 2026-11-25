"""Reranker Protocol contract tests (rag-protocols-foundation, Task 4).

Parametrized over reranker implementation names (currently only "rrf" —
``RRFReranker``) so that any FUTURE reranker registered in the ``reranker``
fixture must pass the same contract (contract-first: tests pass for ANY
correct implementation, not just the baseline).
"""

from __future__ import annotations

import pytest
from swarmline.protocols import Reranker
from swarmline.rerankers import RRFReranker

_RERANKERS: dict[str, type[Reranker]] = {
    "rrf": RRFReranker,
}


@pytest.fixture(params=list(_RERANKERS))
def reranker(request: pytest.FixtureRequest) -> Reranker:
    return _RERANKERS[request.param]()


class TestRerankerProtocolShape:
    def test_reranker_protocol_shape(self, reranker: Reranker) -> None:
        assert isinstance(reranker, Reranker)


class TestRerankSortedDescending:
    async def test_rerank_returns_ranked_documents_sorted_desc(
        self, reranker: Reranker
    ) -> None:
        documents = ["the cat sat", "quantum chromodynamics", "a cat and a dog"]

        ranked = await reranker.rerank("cat", documents)

        for earlier, later in zip(ranked, ranked[1:], strict=False):
            assert earlier.score >= later.score
        for result in ranked:
            assert 0 <= result.index < len(documents)


class TestRerankRelevance:
    async def test_rerank_query_relevant_doc_ranks_first(
        self, reranker: Reranker
    ) -> None:
        documents = ["the cat sat", "quantum chromodynamics", "a cat and a dog"]

        ranked = await reranker.rerank("cat", documents)

        assert "cat" in documents[ranked[0].index]


class TestRerankTopK:
    async def test_rerank_top_k_limits_results(self, reranker: Reranker) -> None:
        documents = ["doc one", "doc two", "doc three", "doc four"]

        ranked = await reranker.rerank("doc", documents, top_k=2)

        assert len(ranked) == 2

    async def test_rerank_top_k_zero_returns_empty(self, reranker: Reranker) -> None:
        documents = ["doc one", "doc two"]

        ranked = await reranker.rerank("doc", documents, top_k=0)

        assert ranked == []

    async def test_rerank_top_k_none_returns_all(self, reranker: Reranker) -> None:
        documents = ["doc one", "doc two", "doc three"]

        ranked = await reranker.rerank("doc", documents, top_k=None)

        assert len(ranked) == len(documents)


class TestRerankEmptyDocuments:
    async def test_rerank_empty_documents_returns_empty(
        self, reranker: Reranker
    ) -> None:
        ranked = await reranker.rerank("query", [])

        assert ranked == []


class TestRerankPreservesText:
    async def test_rerank_preserves_text_at_index(self, reranker: Reranker) -> None:
        documents = ["alpha beta", "gamma delta", "epsilon zeta"]

        ranked = await reranker.rerank("alpha", documents)

        for result in ranked:
            assert result.text == documents[result.index]


class TestRerankStableTieBreak:
    async def test_rerank_stable_tie_break_by_index(self, reranker: Reranker) -> None:
        # doc1 wins lexically (matches "cat"), doc0 wins positionally (index 0).
        # RRF fuses these swapped ranks into an EXACT tie:
        #   score0 = 1/(K+2) + 1/(K+1)  ==  1/(K+1) + 1/(K+2) = score1.
        # Stable tie-break must then order the tie by original index (0 before 1).
        documents = ["dog", "cat"]

        ranked = await reranker.rerank("cat", documents)

        assert ranked[0].score == pytest.approx(ranked[1].score)  # genuine tie
        assert [result.index for result in ranked] == [0, 1]


class TestRerankDeterminism:
    async def test_rerank_is_deterministic_across_calls(
        self, reranker: Reranker
    ) -> None:
        documents = ["the cat sat", "quantum chromodynamics", "a cat and a dog"]

        first = await reranker.rerank("cat", documents)
        second = await reranker.rerank("cat", documents)

        assert first == second


class TestRerankEmptyQuery:
    async def test_rerank_empty_query_does_not_raise(self, reranker: Reranker) -> None:
        documents = ["first doc", "second doc", "third doc"]

        ranked = await reranker.rerank("", documents)

        assert [result.index for result in ranked] == [0, 1, 2]
