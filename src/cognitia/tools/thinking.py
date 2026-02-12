"""ThinkingTool — CoT + ReAct рассуждение для агентов.

Standalone инструмент: агент вызывает thinking(thought="...", next_steps=["..."])
для структурированного размышления. Результат возвращается в контекст LLM.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from cognitia.runtime.types import ToolSpec

# JSON Schema для thinking tool
_THINKING_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "thought": {
            "type": "string",
            "description": "Рассуждение агента: анализ ситуации, выводы, гипотезы.",
        },
        "next_steps": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Следующие шаги, которые агент планирует предпринять.",
        },
    },
    "required": ["thought", "next_steps"],
}


async def thinking_executor(args: dict) -> str:
    """CoT/ReAct thinking — записывает рассуждение и следующие шаги.

    Агент использует этот инструмент для структурированного мышления.
    Результат возвращается в контекст как tool_result.
    """
    thought = args.get("thought", "")
    next_steps = args.get("next_steps")

    if not thought:
        return json.dumps({"status": "error", "message": "thought не может быть пустым"})

    if not next_steps or not isinstance(next_steps, list) or len(next_steps) == 0:
        return json.dumps({"status": "error", "message": "next_steps обязателен (минимум 1 шаг)"})

    return json.dumps({
        "status": "thought_recorded",
        "thought": thought,
        "next_steps": next_steps,
        "instruction": "Продолжай выполнение на основе этого размышления.",
    })


def create_thinking_tool() -> tuple[ToolSpec, Callable]:
    """Создать ThinkingTool — standalone, без внешних зависимостей.

    Returns:
        Tuple: (ToolSpec, executor callable).
    """
    spec = ToolSpec(
        name="thinking",
        description=(
            "CoT+ReAct: структурированное рассуждение агента. "
            "Используй для анализа ситуации и планирования следующих шагов."
        ),
        parameters=_THINKING_SCHEMA,
    )
    return spec, thinking_executor
