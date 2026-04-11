"""Unit-tests: Pydantic-based structured output - validate, extract schema, retry."""

from __future__ import annotations

import enum
import json
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from swarmline.runtime.structured_output import (
    extract_pydantic_schema,
    try_resolve_structured_output,
    validate_structured_output,
)
from swarmline.runtime.types import RuntimeConfig


# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------


class SimpleModel(BaseModel):
    name: str
    age: int


class Address(BaseModel):
    city: str
    zip_code: str


class NestedModel(BaseModel):
    user: str
    address: Address


class Color(enum.Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class ModelWithEnum(BaseModel):
    label: str
    color: Color


class ModelWithOptional(BaseModel):
    required_field: str
    optional_field: int | None = None


# ---------------------------------------------------------------------------
# validate_structured_output
# ---------------------------------------------------------------------------


class TestValidateStructuredOutput:
    """validate_structured_output parsit JSON and validiruet cherez Pydantic."""

    def test_validate_valid_json_returns_model(self) -> None:
        result = validate_structured_output('{"name": "Alice", "age": 30}', SimpleModel)
        assert isinstance(result, SimpleModel)
        assert result.name == "Alice"
        assert result.age == 30

    def test_validate_invalid_json_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid JSON"):
            validate_structured_output("not json at all", SimpleModel)

    def test_validate_wrong_fields_raises(self) -> None:
        with pytest.raises(ValidationError):
            validate_structured_output('{"wrong_field": "value"}', SimpleModel)

    def test_validate_strips_markdown_fences(self) -> None:
        text = '```json\n{"name": "Bob", "age": 25}\n```'
        result = validate_structured_output(text, SimpleModel)
        assert isinstance(result, SimpleModel)
        assert result.name == "Bob"

    def test_validate_nested_model(self) -> None:
        text = '{"user": "Eve", "address": {"city": "NYC", "zip_code": "10001"}}'
        result = validate_structured_output(text, NestedModel)
        assert isinstance(result, NestedModel)
        assert result.address.city == "NYC"


# ---------------------------------------------------------------------------
# extract_pydantic_schema
# ---------------------------------------------------------------------------


class TestExtractPydanticSchema:
    """extract_pydantic_schema returns JSON Schema from Pydantic models."""

    def test_extract_pydantic_schema_basic(self) -> None:
        schema = extract_pydantic_schema(SimpleModel)
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "age" in schema["properties"]

    def test_extract_pydantic_schema_with_optional(self) -> None:
        schema = extract_pydantic_schema(ModelWithOptional)
        assert "required_field" in schema["properties"]
        assert "optional_field" in schema["properties"]
        # optional_field should NOT be in required
        required = schema.get("required", [])
        assert "required_field" in required
        assert "optional_field" not in required

    def test_extract_pydantic_schema_with_enum(self) -> None:
        schema = extract_pydantic_schema(ModelWithEnum)
        assert "color" in schema["properties"]
        # Pydantic 2 produces $defs or references for enums
        # Just check it's a valid dict with color property
        assert isinstance(schema["properties"]["color"], dict)


# ---------------------------------------------------------------------------
# RuntimeConfig.output_type generates output_format
# ---------------------------------------------------------------------------


class TestRuntimeConfigOutputType:
    """RuntimeConfig(output_type=Model) avtomaticheski zapolnyaet output_format."""

    def test_runtime_config_output_type_generates_schema(self) -> None:
        cfg = RuntimeConfig(
            runtime_name="thin",
            output_type=SimpleModel,
        )
        assert cfg.output_format is not None
        assert cfg.output_format["type"] == "object"
        assert "name" in cfg.output_format["properties"]

    def test_runtime_config_output_format_backward_compat(self) -> None:
        """output_format without output_type works kak ranshe."""
        manual_schema: dict[str, Any] = {
            "type": "object",
            "properties": {"x": {"type": "integer"}},
        }
        cfg = RuntimeConfig(
            runtime_name="thin",
            output_format=manual_schema,
        )
        assert cfg.output_format == manual_schema
        assert cfg.output_type is None

    def test_runtime_config_output_format_not_overridden_by_output_type(self) -> None:
        """If output_format uzhe zadan, output_type NE overwrites ego."""
        manual_schema: dict[str, Any] = {"type": "object", "properties": {}}
        cfg = RuntimeConfig(
            runtime_name="thin",
            output_type=SimpleModel,
            output_format=manual_schema,
        )
        assert cfg.output_format == manual_schema


# ---------------------------------------------------------------------------
# try_resolve_structured_output — retry-oriented resolution
# ---------------------------------------------------------------------------


class TestTryResolveStructuredOutput:
    """try_resolve_structured_output: (result, error) tuple for retry logic."""

    def test_retry_on_invalid_then_success(self) -> None:
        """Invalid tekst -> (None, error), valid -> (model, None)."""
        # First attempt: invalid
        result, error = try_resolve_structured_output(
            "not json", {"type": "object"}, SimpleModel
        )
        assert result is None
        assert error is not None
        assert "Invalid JSON" in error

        # Second attempt: valid
        valid_text = json.dumps({"name": "Alice", "age": 30})
        result, error = try_resolve_structured_output(
            valid_text, {"type": "object"}, SimpleModel
        )
        assert error is None
        assert isinstance(result, SimpleModel)
        assert result.name == "Alice"

    def test_retry_max_exceeded_returns_error(self) -> None:
        """Vse popytki invalid -> kazhdaya returns (None, error)."""
        attempts = 3
        for _ in range(attempts):
            result, error = try_resolve_structured_output(
                "still not json", {"type": "object"}, SimpleModel
            )
            assert result is None
            assert error is not None

    def test_resolve_without_output_type_no_error(self) -> None:
        """Without output_type - fallback on extract, oshibok not byvaet."""
        result, error = try_resolve_structured_output(
            '{"x": 42}', {"type": "object"}, None
        )
        assert error is None
        assert result == {"x": 42}

    def test_resolve_validation_error_returns_error_message(self) -> None:
        """JSON valid, no not matchit schema -> error message."""
        result, error = try_resolve_structured_output(
            '{"wrong": "field"}', {"type": "object"}, SimpleModel
        )
        assert result is None
        assert error is not None
