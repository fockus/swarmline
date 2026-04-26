"""Helpers for portable structured output in Thin/DeepAgents runtimes."""

from __future__ import annotations

import json
from typing import Any, Protocol, cast

from swarmline.runtime.thin.parsers import (
    strip_markdown_fences as _strip_markdown_fences,
)


class _StructuredOutputModel(Protocol):
    """Structured Output Model protocol."""

    @classmethod
    def model_validate_json(cls, json_data: str) -> Any: ...

    @classmethod
    def model_json_schema(cls) -> dict[str, Any]: ...


def validate_structured_output(text: str, output_type: _StructuredOutputModel) -> Any:
    """Parse JSON from text and validate against a Pydantic model.

    Strips markdown fences before parsing. Returns a validated model instance.

    Raises:
      ValueError: if text is not valid JSON.
      pydantic.ValidationError: if JSON does not match the model schema.
    """
    cleaned = _strip_markdown_fences(text).strip()
    try:
        json.loads(cleaned)  # validate JSON syntax first
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    return output_type.model_validate_json(cleaned)


def extract_pydantic_schema(output_type: _StructuredOutputModel) -> dict[str, Any]:
    """Extract JSON Schema dict from a Pydantic model class."""
    return output_type.model_json_schema()


def resolve_structured_output(
    text: str,
    output_format: dict[str, Any] | None,
    output_type: type | None,
) -> Any | None:
    """Resolve structured output: validate via Pydantic if output_type set, else extract JSON.

    Returns:
      - Pydantic model instance if output_type is set and validation succeeds
      - dict/list if output_format is set (no output_type) and JSON parses
      - None if no structured output configured

    Raises:
      ValueError: if output_type is set but text is not valid JSON
      pydantic.ValidationError: if output_type is set but JSON doesn't match schema
    """
    if output_type is not None:
        model = cast(_StructuredOutputModel, output_type)
        return validate_structured_output(text, model)
    return extract_structured_output(text, output_format)


def try_resolve_structured_output(
    text: str,
    output_format: dict[str, Any] | None,
    output_type: type | None,
) -> tuple[Any | None, str | None]:
    """Try to resolve structured output, returning (result, error_message).

    If output_type is set and validation fails, returns (None, error_str).
    If no output_type, falls back to extract_structured_output (never errors).
    On success returns (parsed_output, None).
    """
    if output_type is not None:
        try:
            model = cast(_StructuredOutputModel, output_type)
            parsed = validate_structured_output(text, model)
            return parsed, None
        except (ValueError, Exception) as exc:
            return None, str(exc)
    return extract_structured_output(text, output_format), None


def append_structured_output_instruction(
    system_prompt: str,
    output_format: dict[str, Any] | None,
    *,
    final_response_field: str | None = None,
) -> str:
    """Append structured output instruction."""
    schema = normalize_output_schema(output_format)
    if schema is None:
        return system_prompt

    schema_json = json.dumps(schema, ensure_ascii=False)
    if final_response_field is not None:
        instruction = (
            "\n\n## Structured output\n"
            "Your final response must be valid JSON conforming to the schema below.\n"
            f"Place the entire JSON in the `{final_response_field}` field, with no markdown or explanations.\n"
            f"Schema: {schema_json}"
        )
    else:
        instruction = (
            "\n\n## Structured output\n"
            "Your final response must be valid JSON only, conforming to the schema below.\n"
            "No markdown wrapping and no explanations.\n"
            f"Schema: {schema_json}"
        )
    return f"{system_prompt}{instruction}"


def extract_structured_output(
    text: str,
    output_format: dict[str, Any] | None,
) -> Any | None:
    """Extract structured output."""
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


def normalize_output_schema(
    output_format: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize output schema."""
    if not output_format:
        return None
    if output_format.get("type") == "json_schema":
        json_schema = output_format.get("json_schema")
        if isinstance(json_schema, dict):
            schema = json_schema.get("schema")
            return schema if isinstance(schema, dict) else None
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
