"""LLM-based SummaryGenerator - generate a rolling summary via an LLM call.

Uses AgentRuntime.run() to generate a short conversation summary.
Falls back to TemplateSummaryGenerator if the LLM fails.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

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
    """

    def __init__(
        self,
        llm_call: Callable[..., Any] | None = None,
        fallback_max_messages: int = 10,
    ) -> None:
        """Initialize the generator.

        Args:
            llm_call: async callable(prompt: str, messages_text: str) -> str.
                      If None, fall back to the template immediately.
            fallback_max_messages: Max messages for the fallback summarizer.
        """
        self._llm_call = llm_call
        self._fallback = TemplateSummaryGenerator(max_messages=fallback_max_messages)

    def summarize(self, messages: list[MemoryMessage]) -> str:
        """Sync wrapper for Protocol compatibility. Delegates to the fallback.

        Use asummarize() for the async LLM path.
        """
        return self._fallback.summarize(messages)

    async def asummarize(self, messages: list[MemoryMessage]) -> str:
        """Async summarization via LLM with fallback.

        Args:
            messages: Conversation messages (oldest to newest).

        Returns:
            Summary text (~1000-1500 characters) or the fallback template.
        """
        if not messages:
            return ""

        if not self._llm_call:
            return self._fallback.summarize(messages)

        # Build the conversation text for the LLM
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
