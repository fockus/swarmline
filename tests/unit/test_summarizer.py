"""Тесты для SummaryGenerator — генерация rolling summary из сообщений.

TDD Red phase: тесты описывают контракт ДО реализации.
"""

from __future__ import annotations

from cognitia.memory.types import MemoryMessage


class TestTemplateSummaryGenerator:
    """Template-based SummaryGenerator (MVP, без LLM)."""

    def test_empty_messages_returns_empty(self) -> None:
        """Пустой список сообщений -> пустая строка."""
        from cognitia.memory.summarizer import TemplateSummaryGenerator

        gen = TemplateSummaryGenerator()
        result = gen.summarize([])
        assert result == ""

    def test_single_user_message(self) -> None:
        """Одно user-сообщение -> краткий summary."""
        from cognitia.memory.summarizer import TemplateSummaryGenerator

        gen = TemplateSummaryGenerator()
        messages = [MemoryMessage(role="user", content="Мой доход 120 000 рублей")]
        result = gen.summarize(messages)
        assert "120 000" in result
        assert len(result) > 10

    def test_multi_turn_conversation(self) -> None:
        """Несколько turn -> summary содержит ключевые моменты."""
        from cognitia.memory.summarizer import TemplateSummaryGenerator

        gen = TemplateSummaryGenerator()
        messages = [
            MemoryMessage(role="user", content="Подбери вклад на 7 млн рублей на 3 месяца"),
            MemoryMessage(role="assistant", content="Вот топ-5 вкладов с максимальной ставкой..."),
            MemoryMessage(role="user", content="Без пополнения, максимальная доходность"),
            MemoryMessage(role="assistant", content="Рекомендую разделить на 3 банка..."),
        ]
        result = gen.summarize(messages)
        assert "7 млн" in result or "вклад" in result.lower()
        assert len(result) > 20

    def test_truncates_long_messages(self) -> None:
        """Длинные сообщения обрезаются в summary."""
        from cognitia.memory.summarizer import TemplateSummaryGenerator

        gen = TemplateSummaryGenerator(max_message_chars=50)
        messages = [
            MemoryMessage(role="user", content="A" * 200),
        ]
        result = gen.summarize(messages)
        # Summary не должен содержать полные 200 символов
        assert len(result) < 200

    def test_respects_max_messages(self) -> None:
        """Учитывает только последние N сообщений."""
        from cognitia.memory.summarizer import TemplateSummaryGenerator

        gen = TemplateSummaryGenerator(max_messages=2)
        messages = [
            MemoryMessage(role="user", content="Старое сообщение"),
            MemoryMessage(role="assistant", content="Старый ответ"),
            MemoryMessage(role="user", content="Новое сообщение"),
            MemoryMessage(role="assistant", content="Новый ответ"),
        ]
        result = gen.summarize(messages)
        assert "Новое" in result
        # Старое сообщение не должно попасть в summary
        assert "Старое" not in result
