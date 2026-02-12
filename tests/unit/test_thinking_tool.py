"""Тесты ThinkingTool — CoT + ReAct рассуждение.

TDD: RED → GREEN → REFACTOR.
"""

from __future__ import annotations

import json


class TestThinkingTool:
    """thinking executor — standalone, без внешних зависимостей."""

    async def test_basic_thought(self) -> None:
        """Мысль записывается и возвращается в JSON."""
        from cognitia.tools.thinking import thinking_executor

        result = await thinking_executor({
            "thought": "Мне нужно найти файл конфигурации.",
            "next_steps": ["Поиск по glob *.yaml", "Прочитать содержимое"],
        })
        data = json.loads(result)

        assert data["status"] == "thought_recorded"
        assert data["thought"] == "Мне нужно найти файл конфигурации."
        assert data["next_steps"] == ["Поиск по glob *.yaml", "Прочитать содержимое"]
        assert "instruction" in data

    async def test_empty_thought_returns_error(self) -> None:
        """Пустая мысль → error."""
        from cognitia.tools.thinking import thinking_executor

        result = await thinking_executor({"thought": "", "next_steps": ["step"]})
        data = json.loads(result)
        assert data["status"] == "error"

    async def test_missing_next_steps_returns_error(self) -> None:
        """Без next_steps → error."""
        from cognitia.tools.thinking import thinking_executor

        result = await thinking_executor({"thought": "think"})
        data = json.loads(result)
        assert data["status"] == "error"

    async def test_empty_next_steps_returns_error(self) -> None:
        """Пустой массив next_steps → error."""
        from cognitia.tools.thinking import thinking_executor

        result = await thinking_executor({"thought": "think", "next_steps": []})
        data = json.loads(result)
        assert data["status"] == "error"

    def test_tool_spec(self) -> None:
        """ThinkingTool возвращает корректный ToolSpec."""
        from cognitia.tools.thinking import create_thinking_tool

        spec, executor = create_thinking_tool()

        assert spec.name == "thinking"
        assert "thought" in json.dumps(spec.parameters)
        assert "next_steps" in json.dumps(spec.parameters)
        assert callable(executor)

    def test_schema_required_fields(self) -> None:
        """JSON Schema содержит required fields."""
        from cognitia.tools.thinking import create_thinking_tool

        spec, _ = create_thinking_tool()
        schema = spec.parameters

        assert "thought" in schema["properties"]
        assert "next_steps" in schema["properties"]
        assert "thought" in schema["required"]
        assert "next_steps" in schema["required"]
        assert schema["properties"]["next_steps"]["minItems"] == 1
