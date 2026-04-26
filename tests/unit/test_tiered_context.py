"""Tests for TieredContextManager and TieredRetriever.

TDD: tests for L0/L1/L2 generation, search, budget, and retriever.
Uses InMemory MemoryBankProvider (no disk/DB needed).
"""

from __future__ import annotations

from swarmline.memory_bank.tiered import (
    SimpleTierGenerator,
    TieredContextManager,
    _estimate_tokens,
    _truncate_to_tokens,
)


# ---------------------------------------------------------------------------
# Helpers: in-memory MemoryBankProvider
# ---------------------------------------------------------------------------


class InMemoryBankProvider:
    """Minimal MemoryBankProvider for testing."""

    def __init__(self) -> None:
        self._files: dict[str, str] = {}

    async def read_file(self, path: str) -> str | None:
        return self._files.get(path)

    async def write_file(self, path: str, content: str) -> None:
        self._files[path] = content

    async def append_to_file(self, path: str, content: str) -> None:
        self._files[path] = self._files.get(path, "") + content

    async def list_files(self, prefix: str = "") -> list[str]:
        return [p for p in sorted(self._files) if p.startswith(prefix)]

    async def delete_file(self, path: str) -> None:
        self._files.pop(path, None)


class MockLlmGenerator:
    """Mock TierGenerator that prepends tier type to content."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def generate(self, prompt: str, content: str) -> str:
        self.calls.append((prompt, content))
        if "one-line" in prompt.lower() or "100 tokens" in prompt.lower():
            return f"[L0] {content[:50]}"
        return f"[L1] {content[:200]}"


# ---------------------------------------------------------------------------
# Token estimation helpers
# ---------------------------------------------------------------------------


class TestTokenHelpers:
    def test_estimate_tokens(self) -> None:
        assert _estimate_tokens("") == 1
        assert _estimate_tokens("hello world") > 0

    def test_truncate_within_budget(self) -> None:
        text = "short"
        assert _truncate_to_tokens(text, 100) == text

    def test_truncate_exceeds_budget(self) -> None:
        text = "x" * 1000
        result = _truncate_to_tokens(text, 10)
        assert len(result) <= 44  # 10*4 + 3 ("...")
        assert result.endswith("...")


# ---------------------------------------------------------------------------
# SimpleTierGenerator
# ---------------------------------------------------------------------------


class TestSimpleTierGenerator:
    async def test_l0_returns_first_line(self) -> None:
        gen = SimpleTierGenerator()
        content = "First line\nSecond line\nThird line"
        result = await gen.generate(
            "Create a one-line abstract (max 100 tokens)", content
        )
        assert "First line" in result

    async def test_l1_returns_truncated(self) -> None:
        gen = SimpleTierGenerator()
        content = "x" * 20000
        result = await gen.generate(
            "Create a concise overview (max 2000 tokens)", content
        )
        assert len(result) < len(content)


# ---------------------------------------------------------------------------
# TieredContextManager: on_file_written
# ---------------------------------------------------------------------------


class TestOnFileWritten:
    async def test_generates_l0_and_l1(self) -> None:
        """Writing a file generates L0 and L1 tiers."""
        provider = InMemoryBankProvider()
        gen = MockLlmGenerator()
        manager = TieredContextManager(provider, generator=gen)

        await manager.on_file_written("plans/feature.md", "Detailed feature spec")

        l0 = await provider.read_file(".tiers/plans/feature.md.l0")
        l1 = await provider.read_file(".tiers/plans/feature.md.l1")
        assert l0 is not None
        assert l1 is not None
        assert "[L0]" in l0
        assert "[L1]" in l1

    async def test_skips_tier_files(self) -> None:
        """Writing to .tiers/ doesn't generate tiers recursively."""
        provider = InMemoryBankProvider()
        gen = MockLlmGenerator()
        manager = TieredContextManager(provider, generator=gen)

        await manager.on_file_written(".tiers/something.l0", "content")
        assert len(gen.calls) == 0

    async def test_skips_empty_content(self) -> None:
        """Empty content doesn't generate tiers."""
        provider = InMemoryBankProvider()
        gen = MockLlmGenerator()
        manager = TieredContextManager(provider, generator=gen)

        await manager.on_file_written("empty.md", "   ")
        assert len(gen.calls) == 0

    async def test_generator_called_twice(self) -> None:
        """Generator is called once for L0 and once for L1."""
        provider = InMemoryBankProvider()
        gen = MockLlmGenerator()
        manager = TieredContextManager(provider, generator=gen)

        await manager.on_file_written("doc.md", "Some content")
        assert len(gen.calls) == 2


# ---------------------------------------------------------------------------
# TieredContextManager: get_tiered
# ---------------------------------------------------------------------------


class TestGetTiered:
    async def test_l2_returns_original(self) -> None:
        provider = InMemoryBankProvider()
        await provider.write_file("doc.md", "original content")
        manager = TieredContextManager(provider)

        result = await manager.get_tiered("doc.md", "L2")
        assert result == "original content"

    async def test_l0_returns_tier(self) -> None:
        provider = InMemoryBankProvider()
        await provider.write_file(".tiers/doc.md.l0", "abstract")
        manager = TieredContextManager(provider)

        result = await manager.get_tiered("doc.md", "L0")
        assert result == "abstract"

    async def test_l1_returns_tier(self) -> None:
        provider = InMemoryBankProvider()
        await provider.write_file(".tiers/doc.md.l1", "overview")
        manager = TieredContextManager(provider)

        result = await manager.get_tiered("doc.md", "L1")
        assert result == "overview"

    async def test_missing_tier_returns_none(self) -> None:
        provider = InMemoryBankProvider()
        manager = TieredContextManager(provider)

        result = await manager.get_tiered("nonexistent.md", "L0")
        assert result is None


# ---------------------------------------------------------------------------
# TieredContextManager: search
# ---------------------------------------------------------------------------


class TestSearch:
    async def test_search_finds_matching_files(self) -> None:
        provider = InMemoryBankProvider()
        manager = TieredContextManager(provider)

        # Write L0 and L1 tiers manually
        await provider.write_file(
            ".tiers/plans/auth.md.l0", "authentication login security"
        )
        await provider.write_file(
            ".tiers/plans/auth.md.l1", "Auth module overview with JWT tokens"
        )
        await provider.write_file(
            ".tiers/plans/ui.md.l0", "user interface components layout"
        )
        await provider.write_file(
            ".tiers/plans/ui.md.l1", "UI components design system"
        )

        results = await manager.search("authentication security")
        assert len(results) >= 1
        assert results[0].path == "plans/auth.md"
        assert results[0].tier == "L1"

    async def test_search_empty_query(self) -> None:
        provider = InMemoryBankProvider()
        manager = TieredContextManager(provider)
        assert await manager.search("") == []

    async def test_search_no_matches(self) -> None:
        provider = InMemoryBankProvider()
        await provider.write_file(".tiers/doc.md.l0", "python programming")
        manager = TieredContextManager(provider)

        results = await manager.search("quantum physics")
        assert results == []

    async def test_search_respects_budget(self) -> None:
        provider = InMemoryBankProvider()
        manager = TieredContextManager(provider)

        # Create many L0/L1 entries
        for i in range(20):
            await provider.write_file(f".tiers/doc{i}.md.l0", f"keyword topic{i}")
            await provider.write_file(
                f".tiers/doc{i}.md.l1", f"Overview of topic{i} " * 100
            )

        results = await manager.search("keyword", budget_tokens=500)
        total_tokens = sum(e.token_count for e in results)
        assert total_tokens <= 500


# ---------------------------------------------------------------------------
# TieredContextManager: build_context
# ---------------------------------------------------------------------------


class TestBuildContext:
    async def test_build_context_includes_toc(self) -> None:
        provider = InMemoryBankProvider()
        manager = TieredContextManager(provider)

        await provider.write_file(".tiers/plans/a.md.l0", "Plan A abstract")
        await provider.write_file(".tiers/plans/b.md.l0", "Plan B abstract")

        ctx = await manager.build_context(budget_tokens=5000)
        assert "Memory Bank Index" in ctx
        assert "plans/a.md" in ctx
        assert "plans/b.md" in ctx

    async def test_build_context_expands_l1(self) -> None:
        provider = InMemoryBankProvider()
        manager = TieredContextManager(provider)

        await provider.write_file(".tiers/doc.md.l0", "Doc abstract")
        await provider.write_file(".tiers/doc.md.l1", "Detailed overview of document")

        ctx = await manager.build_context(budget_tokens=5000)
        assert "Detailed overview" in ctx

    async def test_build_context_empty_bank(self) -> None:
        provider = InMemoryBankProvider()
        manager = TieredContextManager(provider)

        ctx = await manager.build_context(budget_tokens=5000)
        assert ctx == ""

    async def test_build_context_respects_budget(self) -> None:
        provider = InMemoryBankProvider()
        manager = TieredContextManager(provider)

        for i in range(50):
            await provider.write_file(f".tiers/doc{i}.md.l0", f"Abstract {i}")
            await provider.write_file(f".tiers/doc{i}.md.l1", f"Overview {i} " * 200)

        ctx = await manager.build_context(budget_tokens=1000)
        assert _estimate_tokens(ctx) <= 1100  # allow small margin


# ---------------------------------------------------------------------------
# TieredRetriever (Retriever protocol compliance)
# ---------------------------------------------------------------------------


class TestTieredRetriever:
    async def test_implements_retriever_protocol(self) -> None:
        from swarmline.rag import Retriever, TieredRetriever

        provider = InMemoryBankProvider()
        manager = TieredContextManager(provider)
        retriever = TieredRetriever(manager)
        assert isinstance(retriever, Retriever)

    async def test_retrieve_returns_documents(self) -> None:
        from swarmline.rag import TieredRetriever

        provider = InMemoryBankProvider()
        manager = TieredContextManager(provider)

        await provider.write_file(".tiers/auth.md.l0", "authentication login")
        await provider.write_file(".tiers/auth.md.l1", "Auth module with JWT")

        retriever = TieredRetriever(manager)
        docs = await retriever.retrieve("authentication", top_k=5)
        assert len(docs) >= 1
        assert docs[0].metadata["path"] == "auth.md"
        assert docs[0].metadata["tier"] == "L1"
        assert docs[0].score is None  # score not set (no relevance ranking)

    async def test_retrieve_empty_query(self) -> None:
        from swarmline.rag import TieredRetriever

        provider = InMemoryBankProvider()
        manager = TieredContextManager(provider)
        retriever = TieredRetriever(manager)
        docs = await retriever.retrieve("")
        assert docs == []

    async def test_rejects_wrong_type(self) -> None:
        """TieredRetriever rejects non-TieredContextManager."""
        import pytest
        from swarmline.rag import TieredRetriever

        with pytest.raises(TypeError, match="Expected TieredContextManager"):
            TieredRetriever("not a manager")


# ---------------------------------------------------------------------------
# Edge cases and security
# ---------------------------------------------------------------------------


class TestEdgeCases:
    async def test_on_file_written_traversal_blocked(self) -> None:
        """Path traversal in on_file_written is rejected."""
        provider = InMemoryBankProvider()
        gen = MockLlmGenerator()
        manager = TieredContextManager(provider, generator=gen)

        await manager.on_file_written("../../etc/passwd", "hacked")
        assert len(gen.calls) == 0  # generator never called

    async def test_on_file_written_absolute_path_blocked(self) -> None:
        """Absolute path in on_file_written is rejected."""
        provider = InMemoryBankProvider()
        gen = MockLlmGenerator()
        manager = TieredContextManager(provider, generator=gen)

        await manager.on_file_written("/etc/passwd", "hacked")
        assert len(gen.calls) == 0

    async def test_build_context_zero_budget(self) -> None:
        """build_context with 0 budget returns truncated or empty."""
        provider = InMemoryBankProvider()
        await provider.write_file(".tiers/doc.md.l0", "abstract")
        manager = TieredContextManager(provider)

        ctx = await manager.build_context(budget_tokens=0)
        # Should return something (truncated TOC) or empty
        assert isinstance(ctx, str)
