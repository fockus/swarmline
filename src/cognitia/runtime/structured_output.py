"""Helpers для portable structured output в thin/deepagents runtimes."""

from __future__ import annotations

import json
from typing import Any

from cognitia.runtime.thin.parsers import strip_markdown_fences as _strip_markdown_fences


def append_structured_output_instruction(
    system_prompt: str,
    output_format: dict[str, Any] | None,
    *,
    final_response_field: str | None = None,
) -> str:
    """Добавить в system prompt инструкции для structured output."""
    schema = normalize_output_schema(output_format)
    if schema is None:
        return system_prompt

    schema_json = json.dumps(schema, ensure_ascii=False)
    if final_response_field is not None:
        instruction = (
            "\n\n## Structured output\n"
            "Финальный ответ должен соответствовать JSON Schema ниже.\n"
            f"Помести JSON целиком в поле `{final_response_field}` без markdown и пояснений.\n"
            f"Schema: {schema_json}"
        )
    else:
        instruction = (
            "\n\n## Structured output\n"
            "Финальный ответ должен быть только валидным JSON, соответствующим JSON Schema ниже.\n"
            "Без markdown-обёртки и без пояснений.\n"
            f"Schema: {schema_json}"
        )
    return f"{system_prompt}{instruction}"


def extract_structured_output(
    text: str,
    output_format: dict[str, Any] | None,
) -> Any | None:
    """Извлечь JSON structured output из финального текста."""
    if not output_format:
        return None

    cleaned = _strip_markdown_fences(text).strip()
    if not cleaned:
        return None

    for candidate in (cleaned, _extract_first_json_value(cleaned)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def normalize_output_schema(output_format: dict[str, Any] | None) -> dict[str, Any] | None:
    """Нормализовать facade/output_format в обычную JSON Schema."""
    if not output_format:
        return None
    if output_format.get("type") == "json_schema":
        schema = output_format.get("schema")
        return schema if isinstance(schema, dict) else None
    return output_format


def _extract_first_json_value(text: str) -> str | None:
    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char not in '{["-0123456789tfn':
            continue
        try:
            _, end = decoder.raw_decode(text[idx:])
            return text[idx : idx + end]
        except json.JSONDecodeError:
            continue
    return None
