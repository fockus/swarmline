"""Embedder Protocol contract tests (rag-protocols-foundation, Task 2).

Parametrized over embedder implementation names (currently only "hash" —
``HashEmbedder``) so that any FUTURE embedder registered in the ``embedder``
fixture must pass the same contract (contract-first: tests pass for ANY
correct implementation, not just the baseline).
"""

from __future__ import annotations

import math

import pytest
from swarmline.embeddings import HashEmbedder
from swarmline.embeddings.baseline import _bucket_sign
from swarmline.protocols import Embedder
from swarmline.skills.embedding_retriever import _cosine_similarity

_EMBEDDERS: dict[str, Embedder] = {
    "hash": HashEmbedder(),
}


@pytest.fixture(params=list(_EMBEDDERS))
def embedder(request: pytest.FixtureRequest) -> Embedder:
    return _EMBEDDERS[request.param]


class TestEmbedderProtocolShape:
    def test_embedder_protocol_shape(self, embedder: Embedder) -> None:
        assert isinstance(embedder, Embedder)


class TestEmbedDimensionality:
    async def test_embed_query_returns_fixed_dim_vector(
        self, embedder: Embedder
    ) -> None:
        vec = await embedder.embed_query("hello world")
        assert isinstance(vec, list)
        assert len(vec) == embedder.dim  # type: ignore[attr-defined]

    async def test_embed_documents_returns_one_vector_per_doc_same_dim(
        self, embedder: Embedder
    ) -> None:
        docs = ["alpha beta", "gamma delta", "epsilon"]
        vectors = await embedder.embed_documents(docs)
        assert len(vectors) == len(docs)
        dim = embedder.dim  # type: ignore[attr-defined]
        for vec in vectors:
            assert len(vec) == dim


class TestEmbedDeterminism:
    async def test_embed_query_is_deterministic(self, embedder: Embedder) -> None:
        text = "the quick brown fox"
        first = await embedder.embed_query(text)
        second = await embedder.embed_query(text)
        assert first == second


class TestEmbedNormalization:
    async def test_embed_query_is_l2_normalized_for_nonempty(
        self, embedder: Embedder
    ) -> None:
        vec = await embedder.embed_query("normalize this text please")
        norm = math.sqrt(sum(x * x for x in vec))
        assert norm == pytest.approx(1.0, abs=1e-6)

    async def test_embed_empty_text_returns_zero_vector_no_error(
        self, embedder: Embedder
    ) -> None:
        vec = await embedder.embed_query("")
        assert all(x == 0.0 for x in vec)


class TestCountTokens:
    def test_count_tokens_positive_for_nonempty_zero_for_empty(
        self, embedder: Embedder
    ) -> None:
        assert embedder.count_tokens("hello there world") > 0
        assert embedder.count_tokens("") == 0


class TestSemanticOrdering:
    async def test_similar_text_more_similar_than_unrelated(
        self, embedder: Embedder
    ) -> None:
        query = "python async programming tutorial"
        near = "python async programming guide"
        far = "grilling recipes for summer barbecue"

        query_vec = await embedder.embed_query(query)
        near_vec = await embedder.embed_query(near)
        far_vec = await embedder.embed_query(far)

        sim_near = _cosine_similarity(query_vec, near_vec)
        sim_far = _cosine_similarity(query_vec, far_vec)

        assert sim_near > sim_far


class TestSignedHashIndependence:
    def test_sign_is_independent_of_bucket_parity(self) -> None:
        """Sign must NOT be a function of bucket parity (feature-hash property).

        Regression guard: the earlier implementation derived the sign from
        ``h & 1`` while ``bucket = h % 256`` — so with a power-of-two ``dim``
        the sign was fully determined by bucket parity and colliding tokens
        could never cancel. An independent sign disagrees with bucket parity
        for roughly half the tokens; the buggy version disagreed for zero.
        """
        dim = 256
        disagreements = sum(
            1
            for i in range(200)
            if _bucket_sign(f"token{i}", dim)[1]
            != (1.0 if (_bucket_sign(f"token{i}", dim)[0] & 1) else -1.0)
        )
        assert disagreements > 40
