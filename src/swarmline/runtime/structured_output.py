"""Helpers for portable structured output in Thin/DeepAgents runtimes."""

from __future__ import annotations

import json
from typing import Any, Protocol, cast, runtime_checkable

from swarmline.runtime.thin.parsers import (
    strip_markdown_fences as _strip_markdown_fences,
)


class _StructuredOutputModel(Protocol):
    """Structured Output Model protocol."""

    @classmethod
    def model_validate_json(cls, json_data: str) -> Any: ...

    @classmethod
    def model_json_schema(cls) -> dict[str, Any]: ...


@runtime_checkable
class _EmptyAwareOutput(Protocol):
    """Opt-in protocol for structured outputs that can report semantic emptiness.

    A structured output is **schema-valid** yet **semantically empty** when it parses
    correctly but carries no usable payload (e.g. a selection schema whose ``picks`` list
    is ``[]``). Such a result is a degenerate provider miss — the same retryable failure as
    a parse error — rather than a legitimate "found nothing" answer.

    The contract is entirely opt-in: a schema participates ONLY by defining
    ``is_empty_result(self) -> bool``. Schemas that do not implement the method are never
    inspected and behave byte-for-byte as before. No provider/model knowledge is involved.
    """

    def is_empty_result(self) -> bool: ...


def empty_result_error(output: Any) -> str | None:
    """Return a retry message when an opt-in structured output reports itself empty.

    Returns an informative string when ``output`` implements the :class:`_EmptyAwareOutput`
    protocol and ``is_empty_result()`` is truthy; otherwise ``None``. A buggy predicate that
    raises is treated as "not empty" (fail-safe → ``None``): a faulty emptiness check must
    never break finalization. Outputs without the method are ignored entirely (opt-in).
    """
    if not isinstance(output, _EmptyAwareOutput):
        return None
    try:
        is_empty = output.is_empty_result()
    except Exception:
        return None
    if not is_empty:
        return None
    return (
        "Previous response was schema-valid but semantically empty "
        "(it reported no usable result)."
    )


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
    """Extract JSON Schema dict from a Pydantic model class.

    This is the single funnel every ``output_type`` -> ``output_format``
    derivation goes through (claude_sdk one-shot and conversation dispatch via
    ``_effective_output_format``; portable-runtime structured-output emulation
    for pi_sdk/cli). Callers pass whatever ``AgentConfig.output_type``/
    ``RuntimeConfig.output_type`` holds, which is typed as ``type | None``
    without validating it is actually a Pydantic ``BaseModel`` subclass.

    Raises:
      ValueError: if ``output_type`` does not expose a callable
        ``model_json_schema`` (i.e. is not a Pydantic ``BaseModel`` subclass —
        e.g. a plain dataclass, ``dict``, or ``TypedDict``). Loud-over-silent:
        a bare ``AttributeError`` from ``model_json_schema()`` deep in this
        function would be an unnamed, uninformative failure for a
        configuration mistake every caller can make.
    """
    schema_builder = getattr(output_type, "model_json_schema", None)
    if not callable(schema_builder):
        raise ValueError(
            f"output_type must be a Pydantic BaseModel (got {output_type!r}); "
            "pass a JSON schema via output_format instead."
        )
    return schema_builder()


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


def append_structured_output_instruction_for_mode(
    mode: str,
    system_prompt: str,
    output_format: dict[str, Any] | None,
    *,
    final_response_field: str | None = None,
) -> str:
    """Augment the prompt with the schema when the resolved strategy needs it described in-prompt.

    Structured-output reliability depends on the strategy ``mode``:

    * ``"prompt"`` — no ``response_format`` at all → inject the full instruction (with
      ``final_response_field`` when the strategy wraps the answer in an envelope).
    * ``"native_json_object"`` — ``response_format={"type": "json_object"}`` forces valid-JSON
      SYNTAX but the provider does NOT enforce the schema SHAPE. Without the schema in the prompt
      the model emits an empty / partial object (e.g. a nested ``picks`` list parses to ``[]``).
      Inject the SCHEMA-ONLY instruction: the response IS the structured object (parsed directly),
      so never an envelope field.
    * ``"native_json_schema"`` / ``"none"`` — the provider enforces the full schema (or there is
      none) → return the prompt unchanged.

    This makes ``json_object`` structured output reliable for every swarmline consumer, not only
    those on the portable ``prompt`` strategy.
    """
    if mode == "prompt":
        return append_structured_output_instruction(
            system_prompt, output_format, final_response_field=final_response_field
        )
    if mode == "native_json_object":
        return append_structured_output_instruction(system_prompt, output_format)
    return system_prompt


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
