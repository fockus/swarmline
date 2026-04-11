"""Coverage tests: structured_output - append/extract/normalize/strip."""

from __future__ import annotations

from typing import Any

from swarmline.runtime.structured_output import (
    append_structured_output_instruction,
    extract_structured_output,
    normalize_output_schema,
)


class TestAppendStructuredOutputInstruction:
    """append_structured_output_instruction dobavlyaet JSON Schema instruktsiyu."""

    def test_append_no_format_returns_unchanged(self) -> None:
        result = append_structured_output_instruction("Hello", None)
        assert result == "Hello"

    def test_append_empty_format_returns_unchanged(self) -> None:
        result = append_structured_output_instruction("Hello", {})
        assert result == "Hello"

    def test_append_with_schema(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        result = append_structured_output_instruction("System", schema)
        assert "Structured output" in result
        assert '"name"' in result
        assert "schema" in result.lower()

    def test_append_with_final_response_field(self) -> None:
        schema: dict[str, Any] = {"type": "object", "properties": {}}
        result = append_structured_output_instruction(
            "System", schema, final_response_field="answer"
        )
        assert "`answer`" in result

    def test_append_without_final_response_field(self) -> None:
        schema: dict[str, Any] = {"type": "object", "properties": {}}
        result = append_structured_output_instruction("System", schema)
        assert "valid JSON" in result

    def test_append_json_schema_type_unwrapped(self) -> None:
        output_format: dict[str, Any] = {
            "type": "json_schema",
            "schema": {"type": "object", "properties": {"x": {"type": "integer"}}},
        }
        result = append_structured_output_instruction("System", output_format)
        assert '"x"' in result


class TestExtractStructuredOutput:
    """extract_structured_output parsit JSON from teksta."""

    def test_extract_none_when_no_format(self) -> None:
        assert extract_structured_output('{"a": 1}', None) is None

    def test_extract_none_when_empty_format(self) -> None:
        assert extract_structured_output('{"a": 1}', {}) is None

    def test_extract_plain_json(self) -> None:
        result = extract_structured_output('{"name": "test"}', {"type": "object"})
        assert result == {"name": "test"}

    def test_extract_from_markdown_fence(self) -> None:
        text = '```json\n{"x": 42}\n```'
        result = extract_structured_output(text, {"type": "object"})
        assert result == {"x": 42}

    def test_extract_none_when_empty_text(self) -> None:
        assert extract_structured_output("", {"type": "object"}) is None

    def test_extract_none_when_whitespace_only(self) -> None:
        assert extract_structured_output("   \n  ", {"type": "object"}) is None

    def test_extract_json_embedded_in_text(self) -> None:
        text = 'Here is the result: {"status": "ok"} and more text'
        result = extract_structured_output(text, {"type": "object"})
        assert result == {"status": "ok"}

    def test_extract_json_array(self) -> None:
        result = extract_structured_output("[1, 2, 3]", {"type": "array"})
        assert result == [1, 2, 3]

    def test_extract_returns_none_for_garbage(self) -> None:
        assert extract_structured_output("no json here at all", {"type": "object"}) is None


class TestNormalizeOutputSchema:
    """normalize_output_schema obrabatyvaet json_schema wrapper."""

    def test_normalize_none(self) -> None:
        assert normalize_output_schema(None) is None

    def test_normalize_empty(self) -> None:
        assert normalize_output_schema({}) is None

    def test_normalize_json_schema_type(self) -> None:
        fmt: dict[str, Any] = {
            "type": "json_schema",
            "schema": {"type": "object", "properties": {}},
        }
        result = normalize_output_schema(fmt)
        assert result == {"type": "object", "properties": {}}

    def test_normalize_json_schema_no_schema_key(self) -> None:
        fmt: dict[str, Any] = {"type": "json_schema"}
        assert normalize_output_schema(fmt) is None

    def test_normalize_json_schema_non_dict_schema(self) -> None:
        fmt: dict[str, Any] = {"type": "json_schema", "schema": "not a dict"}
        assert normalize_output_schema(fmt) is None

    def test_normalize_passthrough(self) -> None:
        fmt: dict[str, Any] = {"type": "object", "properties": {"a": {"type": "string"}}}
        assert normalize_output_schema(fmt) == fmt
