"""Tests for LlmSummaryGenerator - LLM-based summarizer with fallback."""

from __future__ import annotations

import pytest
from cognitia.memory.llm_summarizer import LlmSummaryGenerator
from cognitia.memory.types import MemoryMessage


def _make_messages(n: int = 5) -> list[MemoryMessage]:
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append(MemoryMessage(role=role, content=f"Сообщение {i}"))
    return msgs


class TestLlmSummaryGeneratorSync:
    """Sync summarize() - delegates in fallback (TemplateSummaryGenerator)."""

    def test_sync_summarize_returns_text(self) -> None:
        gen = LlmSummaryGenerator()
        msgs = _make_messages(3)
        result = gen.summarize(msgs)
        assert "Сообщение 0" in result
        assert "Сообщение 2" in result

    def test_sync_empty_messages_returns_empty(self) -> None:
        gen = LlmSummaryGenerator()
        assert gen.summarize([]) == ""


class TestLlmSummaryGeneratorAsync:
    """Async asummarize() - LLM-call with fallback."""

    @pytest.mark.asyncio
    async def test_asummarize_calls_llm(self) -> None:
        """LLM-call uses if specified."""
        call_log: list[tuple] = []

        async def fake_llm(prompt: str, dialog: str) -> str:
            call_log.append((prompt, dialog))
            return "Пользователь обсудил финансовый план. Доход 100к, цель 1.5м за 2 года." * 5

        gen = LlmSummaryGenerator(llm_call=fake_llm)
        result = await gen.asummarize(_make_messages(5))

        assert len(call_log) == 1
        assert "финансовый план" in result

    @pytest.mark.asyncio
    async def test_asummarize_fallback_on_error(self) -> None:
        """Error LLM -> fallback on template."""

        async def failing_llm(prompt: str, dialog: str) -> str:
            raise RuntimeError("API error")

        gen = LlmSummaryGenerator(llm_call=failing_llm)
        result = await gen.asummarize(_make_messages(3))

        # Fallback - template format
        assert "[user]" in result or "[assistant]" in result

    @pytest.mark.asyncio
    async def test_asummarize_fallback_on_short_result(self) -> None:
        """Too short answer LLM -> fallback."""

        async def short_llm(prompt: str, dialog: str) -> str:
            return "Ок"  # < 50 characters

        gen = LlmSummaryGenerator(llm_call=short_llm)
        result = await gen.asummarize(_make_messages(3))

        # Fallback - contains real messages
        assert "Сообщение" in result

    @pytest.mark.asyncio
    async def test_asummarize_no_llm_uses_fallback(self) -> None:
        """Without llm_call -> always fallback."""
        gen = LlmSummaryGenerator(llm_call=None)
        result = await gen.asummarize(_make_messages(3))
        assert "Сообщение" in result

    @pytest.mark.asyncio
    async def test_asummarize_empty_messages(self) -> None:
        gen = LlmSummaryGenerator()
        result = await gen.asummarize([])
        assert result == ""
