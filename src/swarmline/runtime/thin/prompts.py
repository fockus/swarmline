"""Prompts module."""

from __future__ import annotations

from swarmline.runtime.types import ToolSpec


def build_react_prompt(
    system_prompt: str,
    tools: list[ToolSpec],
) -> str:
    """Build react prompt."""
    tool_descs = _format_tools(tools)

    return f"""{system_prompt}

## Инструкции по формату ответа

Ты ОБЯЗАН отвечать ТОЛЬКО валидным JSON без markdown-обёртки.
Возможны два варианта:

### Вариант A — вызов инструмента:
{{"type": "tool_call", "tool": {{"name": "<tool_name>", "args": {{...}}, "correlation_id": "c1"}}, "assistant_message": ""}}

### Вариант B — финальный ответ:
{{"type": "final", "final_message": "<полный ответ пользователю>", "citations": [], "next_suggestions": []}}

{tool_descs}

ВАЖНО:
- Отвечай ТОЛЬКО JSON. Никакого текста до или после.
- Если нужно вызвать инструмент — используй вариант A.
- Когда готов дать финальный ответ — используй вариант B.
- Не логируй chain-of-thought. Рассуждай внутренне."""


def build_conversational_prompt(system_prompt: str) -> str:
    """Build conversational prompt."""
    return f"""{system_prompt}

## Инструкции по формату ответа

Ты ОБЯЗАН отвечать ТОЛЬКО валидным JSON:
{{"type": "final", "final_message": "<твой ответ>", "citations": [], "next_suggestions": []}}

ВАЖНО:
- Отвечай ТОЛЬКО JSON. Никакого текста до или после.
- Не логируй chain-of-thought."""


def build_planner_prompt(
    system_prompt: str,
    tools: list[ToolSpec],
) -> str:
    """Build planner prompt."""
    tool_descs = _format_tools(tools)

    return f"""{system_prompt}

## Инструкции по формату ответа

Ты ОБЯЗАН вернуть JSON-план в строгом формате:
{{
  "type": "plan",
  "goal": "<цель плана>",
  "steps": [
    {{
      "id": "step1",
      "title": "<название шага>",
      "mode": "react" или "conversational",
      "tool_hints": ["<имя_инструмента>"],
      "success_criteria": ["<критерий>"],
      "max_iterations": 4
    }}
  ],
  "final_format": "<формат финального ответа>"
}}

{tool_descs}

ВАЖНО:
- Отвечай ТОЛЬКО JSON.
- Каждый шаг — отдельная подзадача.
- mode="react" если шаг требует инструментов, "conversational" если нет."""


def build_plan_step_prompt(
    system_prompt: str,
    step_title: str,
    step_context: str,
    tools: list[ToolSpec],
) -> str:
    """Build plan step prompt."""
    tool_descs = _format_tools(tools)

    return f"""{system_prompt}

## Текущий шаг плана: {step_title}

Контекст предыдущих шагов:
{step_context}

## Инструкции по формату ответа

Ты ОБЯЗАН отвечать ТОЛЬКО валидным JSON:
- Вариант A (вызов инструмента): {{"type": "tool_call", "tool": {{"name": "<tool_name>", "args": {{...}}, "correlation_id": "c1"}}, "assistant_message": ""}}
- Вариант B (результат шага): {{"type": "final", "final_message": "<результат шага>", "citations": [], "next_suggestions": []}}

{tool_descs}

ВАЖНО: Отвечай ТОЛЬКО JSON."""


def build_final_assembly_prompt(
    system_prompt: str,
    plan_goal: str,
    step_results: list[str],
    final_format: str,
) -> str:
    """Build final assembly prompt."""
    results_text = "\n\n".join(f"### Шаг {i + 1}\n{r}" for i, r in enumerate(step_results))

    return f"""{system_prompt}

## Финальная сборка

Цель: {plan_goal}

Результаты шагов:
{results_text}

Формат ответа: {final_format or "Структурированный ответ"}

## Инструкции

Ты ОБЯЗАН ответить ТОЛЬКО валидным JSON:
{{"type": "final", "final_message": "<финальный структурированный ответ>", "citations": [], "next_suggestions": []}}

Собери все результаты шагов в единый связный ответ."""


def _format_tools(tools: list[ToolSpec]) -> str:
    """Format tools."""
    if not tools:
        return "Инструменты: нет доступных."

    lines = ["## Доступные инструменты:"]
    for t in tools:
        lines.append(f"- **{t.name}**: {t.description}")
    return "\n".join(lines)
