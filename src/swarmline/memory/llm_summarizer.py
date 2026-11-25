"""LLM-based SummaryGenerator - generate a rolling summary via an LLM call.

Uses AgentRuntime.run() to generate a short conversation summary.
Falls back to TemplateSummaryGenerator if the LLM fails.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from swarmline.memory.recursive_summary import RecursiveSummarizer
from swarmline.memory.summarizer import TemplateSummaryGenerator
from swarmline.memory.types import MemoryMessage

logger = logging.getLogger(__name__)

_SUMMARIZE_PROMPT = """\
Создай краткий пересказ диалога (~1000-1500 символов).

Обязательно укажи:
- Ключевые факты и цифры (суммы, сроки, проценты)
- Затронутые темы
- Принятые решения и договорённости
- Текущее состояние задач

Формат: сплошной текст, не список. Пиши от третьего лица.
"""


class LlmSummaryGenerator:
    """LLM-based summary generator.

    Accepts a callable for the LLM call (async str -> str).
    Falls back to TemplateSummaryGenerator on error.

    Args:
        llm_call: Async ``(prompt: str, messages_text: str) -> str``.
                  If None, the template fallback is used immediately.
        fallback_max_messages: Max messages for the fallback summarizer.
        token_budget: When set, enables recursive history compression via
                      RecursiveSummarizer before summarizing.  Callers that
                      do not pass this argument retain the existing behaviour.
    """

    def __init__(
        self,
        llm_call: Callable[..., Any] | None = None,
        fallback_max_messages: int = 10,
        token_budget: int | None = None,
    ) -> None:
        self._llm_call = llm_call
        self._fallback = TemplateSummaryGenerator(max_messages=fallback_max_messages)
        self._token_budget = token_budget

    def summarize(self, messages: list[MemoryMessage]) -> str:
        """Sync wrapper for Protocol compatibility. Delegates to the fallback.

        Use asummarize() for the async LLM path.
        """
        return self._fallback.summarize(messages)

    async def asummarize(self, messages: list[MemoryMessage]) -> str:
        """Async summarization via LLM with fallback.

        When *token_budget* was supplied at construction, compresses *messages*
        recursively (via RecursiveSummarizer) before the single-LLM-call path.

        Args:
            messages: Conversation messages (oldest to newest).

        Returns:
            Summary text or the fallback template string.
        """
        if not messages:
            return ""

        if not self._llm_call:
            return self._fallback.summarize(messages)

        # --- Recursive compression path (opt-in via token_budget) ---
        if self._token_budget is not None:
            recursive = RecursiveSummarizer(self._llm_call, self._token_budget)
            compressed = await recursive.asummarize(messages)
            lines: list[str] = []
            for msg in compressed:
                label = "Пользователь" if msg.role == "user" else "Ассистент"
                lines.append(f"{label}: {msg.content}")
            return "\n".join(lines)

        # --- Original single-LLM-call path ---
        dialog_lines: list[str] = []
        for msg in messages:
            label = "Пользователь" if msg.role == "user" else "Ассистент"
            dialog_lines.append(f"{label}: {msg.content}")
        dialog_text = "\n".join(dialog_lines)

        try:
            result = await self._llm_call(_SUMMARIZE_PROMPT, dialog_text)
            if result and len(result) > 50:
                return str(result)
            # Too short a response - fallback
            logger.warning(
                "LLM summary слишком короткий (%d chars), fallback", len(result or "")
            )
            return str(self._fallback.summarize(messages))
        except Exception:
            logger.warning(
                "Ошибка LLM-суммаризации, fallback на template", exc_info=True
            )
            return str(self._fallback.summarize(messages))
