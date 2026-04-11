"""TieredContextManager — L0/L1/L2 context generation and retrieval.

Inspired by OpenViking's tiered context model:
- L0 (~100 tokens): abstract/title for fast recall and search
- L1 (~2000 tokens): overview for decision-making
- L2 (unlimited): full original content

Tiers are stored alongside originals in a `.tiers/` subfolder:
    memory/plans/feature.md        ← L2 (original)
    memory/.tiers/plans/feature.l0 ← L0 abstract
    memory/.tiers/plans/feature.l1 ← L1 overview

Requires a SummaryGenerator (async LLM call) for L0/L1 generation.
Falls back to truncation if LLM is unavailable.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Protocol, runtime_checkable

import structlog

from swarmline.memory_bank.protocols import MemoryBankProvider
from swarmline.memory_bank.types import ContextTier, TieredEntry

_log = structlog.get_logger(component="tiered_context")

_TIERS_PREFIX = ".tiers/"

_L0_PROMPT = """\
Create a one-line abstract (max 100 tokens) of this document.
Include: topic, key entities, purpose. No formatting, just plain text.
"""

_L1_PROMPT = """\
Create a concise overview (max 2000 tokens) of this document.
Include: main points, key facts/numbers, decisions, structure.
Write as continuous text, third person.
"""


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: len/4 + 1 (matches budget.py heuristic)."""
    return len(text) // 4 + 1


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximate token budget."""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


@runtime_checkable
class TierGenerator(Protocol):
    """Async LLM call for generating tier summaries."""

    async def generate(self, prompt: str, content: str) -> str: ...


class SimpleTierGenerator:
    """Fallback tier generator using truncation (no LLM)."""

    async def generate(self, prompt: str, content: str) -> str:
        if "one-line" in prompt.lower() or "100 tokens" in prompt.lower():
            # L0: first line or first 100 tokens
            first_line = content.split("\n", 1)[0].strip()
            return _truncate_to_tokens(first_line, 100) if first_line else content[:400]
        # L1: first ~2000 tokens
        return _truncate_to_tokens(content, 2000)


class TieredContextManager:
    """Manages L0/L1/L2 context tiers for memory bank files.

    Usage:
        manager = TieredContextManager(memory_bank_provider)
        await manager.on_file_written("plans/feature.md", content)
        entries = await manager.search("feature requirements", budget_tokens=3000)
        context = await manager.build_context(budget_tokens=4000)
    """

    def __init__(
        self,
        provider: MemoryBankProvider,
        generator: TierGenerator | None = None,
    ) -> None:
        self._provider = provider
        self._generator = generator or SimpleTierGenerator()

    async def on_file_written(self, path: str, content: str) -> None:
        """Generate L0 and L1 tiers for a newly written file.

        Called after memory_write. Skips tier files themselves.
        Validates path to prevent traversal via tier path injection.
        """
        if path.startswith(_TIERS_PREFIX):
            return

        if not content.strip():
            return

        # Validate path to prevent injection (e.g., "../../etc/passwd")
        if ".." in path.split("/") or path.startswith("/"):
            _log.warning("tiered_invalid_path", path=path)
            return

        _log.info("tiered_generating", path=path)

        # Generate L0 (abstract)
        l0_content = await self._generator.generate(_L0_PROMPT, content)
        l0_path = f"{_TIERS_PREFIX}{path}.l0"
        await self._provider.write_file(l0_path, l0_content)

        # Generate L1 (overview)
        l1_content = await self._generator.generate(_L1_PROMPT, content)
        l1_path = f"{_TIERS_PREFIX}{path}.l1"
        await self._provider.write_file(l1_path, l1_content)

        _log.info(
            "tiered_generated",
            path=path,
            l0_tokens=_estimate_tokens(l0_content),
            l1_tokens=_estimate_tokens(l1_content),
        )

    async def get_tiered(self, path: str, tier: ContextTier) -> str | None:
        """Read a specific tier for a given file path.

        L2 reads the original file. L0/L1 read from .tiers/.
        """
        if tier == "L2":
            return await self._provider.read_file(path)
        suffix = ".l0" if tier == "L0" else ".l1"
        tier_path = f"{_TIERS_PREFIX}{path}{suffix}"
        return await self._provider.read_file(tier_path)

    async def search(
        self,
        query: str,
        budget_tokens: int = 3000,
        top_k: int = 10,
    ) -> list[TieredEntry]:
        """Search memory bank files using L0 abstracts, return L1 content.

        1. List all L0 files
        2. Keyword match query against L0 content
        3. Rank by word overlap score
        4. Fill budget with L1 entries
        """
        if not query.strip():
            return []

        l0_files = await self._provider.list_files(prefix=_TIERS_PREFIX)
        l0_files = [f for f in l0_files if f.endswith(".l0")]

        if not l0_files:
            return []

        query_words = Counter(query.lower().split())

        # Batch-read all L0 files (avoid N+1 sequential IO)
        l0_contents = await asyncio.gather(
            *[self._provider.read_file(p) for p in l0_files]
        )

        scored: list[tuple[str, float, str]] = []  # (original_path, score, l0_content)
        for l0_path, l0_content in zip(l0_files, l0_contents):
            if not l0_content:
                continue

            doc_words = Counter(l0_content.lower().split())
            overlap = sum(
                min(query_words[w], doc_words[w]) for w in query_words if w in doc_words
            )
            if overlap > 0:
                original = l0_path[len(_TIERS_PREFIX) :].removesuffix(".l0")
                scored.append((original, float(overlap), l0_content))

        scored.sort(key=lambda x: x[1], reverse=True)

        # Fill budget with L1 content
        results: list[TieredEntry] = []
        used_tokens = 0

        for original_path, score, l0_content in scored[:top_k]:
            l1_content = await self.get_tiered(original_path, "L1")
            if l1_content is None:
                l1_content = l0_content  # fallback to L0

            tokens = _estimate_tokens(l1_content)
            if used_tokens + tokens > budget_tokens:
                # Try to fit truncated version
                remaining = budget_tokens - used_tokens
                if remaining > 50:
                    l1_content = _truncate_to_tokens(l1_content, remaining)
                    tokens = _estimate_tokens(l1_content)
                else:
                    break

            results.append(TieredEntry(
                path=original_path,
                tier="L1",
                content=l1_content,
                token_count=tokens,
            ))
            used_tokens += tokens

        return results

    async def build_context(self, budget_tokens: int = 4000) -> str:
        """Build a context string from all memory bank files within budget.

        Strategy:
        1. List all L0 files (cheap overview)
        2. Include L0 listing as a "table of contents"
        3. Expand top entries to L1 until budget exhausted
        """
        l0_files = await self._provider.list_files(prefix=_TIERS_PREFIX)
        l0_files = [f for f in l0_files if f.endswith(".l0")]

        if not l0_files:
            return ""

        # Phase 1: Build L0 listing (batch-read, avoid N+1)
        sorted_l0 = sorted(l0_files)
        l0_contents = await asyncio.gather(
            *[self._provider.read_file(p) for p in sorted_l0]
        )

        toc_lines: list[str] = []
        for l0_path, l0_content in zip(sorted_l0, l0_contents):
            original = l0_path[len(_TIERS_PREFIX) :].removesuffix(".l0")
            if l0_content:
                toc_lines.append(f"- {original}: {l0_content.strip()}")

        toc = "## Memory Bank Index\n" + "\n".join(toc_lines)
        used_tokens = _estimate_tokens(toc)

        if used_tokens >= budget_tokens:
            return _truncate_to_tokens(toc, budget_tokens)

        # Phase 2: Expand to L1 for files that fit
        details: list[str] = []
        remaining = budget_tokens - used_tokens

        for l0_path in sorted(l0_files):
            original = l0_path[len(_TIERS_PREFIX) :].removesuffix(".l0")
            l1_content = await self.get_tiered(original, "L1")
            if not l1_content:
                continue

            tokens = _estimate_tokens(l1_content)
            if tokens <= remaining:
                details.append(f"### {original}\n{l1_content}")
                remaining -= tokens
            elif remaining > 100:
                details.append(f"### {original}\n{_truncate_to_tokens(l1_content, remaining)}")
                break

        if details:
            return toc + "\n\n" + "\n\n".join(details)
        return toc
