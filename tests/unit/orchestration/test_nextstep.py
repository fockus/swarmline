"""Tests for NextStep schema and SGR output parser."""

from __future__ import annotations

import json

import pytest
from swarmline.orchestration.nextstep import (
    NextStep,
    nextstep_system_instruction,
    parse_nextstep,
)

# ---------------------------------------------------------------------------
# NextStep model validation
# ---------------------------------------------------------------------------


class TestNextStepModel:
    """NextStep Pydantic model tests."""

    def _valid_data(self, **overrides: object) -> dict:
        base = {
            "current_state": "analyzing user request",
            "plan": ["step 1", "step 2"],
            "options": ["option A", "option B"],
            "reasoning": "because X",
            "action": "do Y",
            "confidence": 0.85,
        }
        base.update(overrides)
        return base

    def test_nextstep_valid_data_creates_instance(self) -> None:
        data = self._valid_data()
        ns = NextStep(**data)
        assert ns.current_state == "analyzing user request"
        assert ns.plan == ["step 1", "step 2"]
        assert ns.options == ["option A", "option B"]
        assert ns.reasoning == "because X"
        assert ns.action == "do Y"
        assert ns.confidence == 0.85

    def test_nextstep_frozen_rejects_mutation(self) -> None:
        ns = NextStep(**self._valid_data())
        with pytest.raises((TypeError, ValueError)):
            ns.action = "changed"  # type: ignore[misc]

    @pytest.mark.parametrize(
        "field", ["current_state", "plan", "options", "reasoning", "action"]
    )
    def test_nextstep_missing_required_field_raises(self, field: str) -> None:
        from pydantic import ValidationError

        data = self._valid_data()
        del data[field]
        with pytest.raises(ValidationError):
            NextStep(**data)

    def test_nextstep_confidence_below_zero_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            NextStep(**self._valid_data(confidence=-0.1))

    def test_nextstep_confidence_above_one_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            NextStep(**self._valid_data(confidence=1.1))

    def test_nextstep_confidence_boundary_zero(self) -> None:
        ns = NextStep(**self._valid_data(confidence=0.0))
        assert ns.confidence == 0.0

    def test_nextstep_confidence_boundary_one(self) -> None:
        ns = NextStep(**self._valid_data(confidence=1.0))
        assert ns.confidence == 1.0

    def test_nextstep_json_roundtrip(self) -> None:
        ns = NextStep(**self._valid_data())
        json_str = ns.model_dump_json()
        restored = NextStep.model_validate_json(json_str)
        assert restored == ns

    def test_nextstep_has_json_schema(self) -> None:
        schema = NextStep.model_json_schema()
        assert "properties" in schema
        assert "current_state" in schema["properties"]


# ---------------------------------------------------------------------------
# parse_nextstep
# ---------------------------------------------------------------------------


class TestParseNextStep:
    """parse_nextstep tolerant parser tests."""

    def _valid_json(self) -> str:
        return json.dumps(
            {
                "current_state": "s",
                "plan": ["a"],
                "options": ["b"],
                "reasoning": "r",
                "action": "act",
                "confidence": 0.9,
            }
        )

    def test_parse_nextstep_valid_json_returns_instance(self) -> None:
        result = parse_nextstep(self._valid_json())
        assert result is not None
        assert isinstance(result, NextStep)
        assert result.action == "act"

    def test_parse_nextstep_markdown_fences_stripped(self) -> None:
        text = f"```json\n{self._valid_json()}\n```"
        result = parse_nextstep(text)
        assert result is not None
        assert result.action == "act"

    def test_parse_nextstep_invalid_json_returns_none(self) -> None:
        assert parse_nextstep("not json at all") is None

    def test_parse_nextstep_partial_json_returns_none(self) -> None:
        assert parse_nextstep('{"current_state": "s"}') is None

    def test_parse_nextstep_empty_string_returns_none(self) -> None:
        assert parse_nextstep("") is None

    def test_parse_nextstep_missing_confidence_returns_none(self) -> None:
        data = {
            "current_state": "s",
            "plan": ["a"],
            "options": ["b"],
            "reasoning": "r",
            "action": "act",
        }
        assert parse_nextstep(json.dumps(data)) is None

    def test_parse_nextstep_with_surrounding_text(self) -> None:
        text = f"Here is the result:\n```\n{self._valid_json()}\n```\nDone."
        result = parse_nextstep(text)
        assert result is not None

    def test_parse_nextstep_whitespace_only_returns_none(self) -> None:
        assert parse_nextstep("   \n\t  ") is None

    def test_parse_nextstep_none_like_empty_returns_none(self) -> None:
        assert parse_nextstep("") is None
        assert parse_nextstep("  ") is None

    def test_parse_nextstep_confidence_out_of_range_returns_none(self) -> None:
        data = {
            "current_state": "s",
            "plan": ["a"],
            "options": ["b"],
            "reasoning": "r",
            "action": "act",
            "confidence": 5.0,
        }
        assert parse_nextstep(json.dumps(data)) is None

    def test_parse_nextstep_extra_fields_accepted(self) -> None:
        data = {
            "current_state": "s",
            "plan": ["a"],
            "options": ["b"],
            "reasoning": "r",
            "action": "act",
            "confidence": 0.5,
            "extra_field": "ignored",
        }
        result = parse_nextstep(json.dumps(data))
        assert result is not None
        assert result.confidence == 0.5

    def test_parse_nextstep_json_in_prose_no_fences(self) -> None:
        valid = self._valid_json()
        text = f"The agent decided:\n{valid}\nThat was the output."
        result = parse_nextstep(text)
        assert result is not None
        assert result.action == "act"

    @pytest.mark.parametrize(
        ("label", "text", "expected_none"),
        [
            ("valid_plain", None, False),  # replaced in fixture
            ("valid_fenced", None, False),
            ("garbage_text", "hello world no json", True),
            ("empty", "", True),
            ("partial_json", '{"current_state": "s"}', True),
            ("broken_json", '{"current_state": "s",}', True),
            ("array_not_object", '[{"current_state": "s"}]', True),
            ("confidence_negative", None, True),
            ("confidence_over_one", None, True),
        ],
        ids=lambda x: x if isinstance(x, str) else "",
    )
    def test_parse_nextstep_parametrized_variants(
        self, label: str, text: str | None, expected_none: bool
    ) -> None:
        valid_data = {
            "current_state": "s",
            "plan": ["a"],
            "options": ["b"],
            "reasoning": "r",
            "action": "act",
            "confidence": 0.9,
        }
        if label == "valid_plain":
            text = json.dumps(valid_data)
        elif label == "valid_fenced":
            text = f"```json\n{json.dumps(valid_data)}\n```"
        elif label == "confidence_negative":
            valid_data["confidence"] = -0.5
            text = json.dumps(valid_data)
        elif label == "confidence_over_one":
            valid_data["confidence"] = 2.0
            text = json.dumps(valid_data)

        assert text is not None
        result = parse_nextstep(text)
        if expected_none:
            assert result is None, f"Expected None for {label}, got {result}"
        else:
            assert result is not None, f"Expected NextStep for {label}, got None"
            assert isinstance(result, NextStep)


# ---------------------------------------------------------------------------
# nextstep_system_instruction
# ---------------------------------------------------------------------------


class TestNextStepSystemInstruction:
    """nextstep_system_instruction tests."""

    def test_nextstep_system_instruction_returns_nonempty(self) -> None:
        instruction = nextstep_system_instruction()
        assert isinstance(instruction, str)
        assert len(instruction) > 50

    def test_nextstep_system_instruction_contains_schema_fields(self) -> None:
        instruction = nextstep_system_instruction()
        for field_name in (
            "current_state",
            "plan",
            "options",
            "reasoning",
            "action",
            "confidence",
        ):
            assert field_name in instruction

    def test_nextstep_system_instruction_contains_json_schema(self) -> None:
        instruction = nextstep_system_instruction()
        assert "Schema:" in instruction
        assert '"properties"' in instruction or "properties" in instruction

    def test_nextstep_system_instruction_contains_sgr_header(self) -> None:
        instruction = nextstep_system_instruction()
        assert "SGR NextStep" in instruction


# ---------------------------------------------------------------------------
# RuntimeConfig.sgr_enabled
# ---------------------------------------------------------------------------


class TestRuntimeConfigSgrEnabled:
    """sgr_enabled field on RuntimeConfig."""

    def test_sgr_enabled_defaults_false(self) -> None:
        from swarmline.runtime.types import RuntimeConfig

        cfg = RuntimeConfig()
        assert cfg.sgr_enabled is False

    def test_sgr_enabled_set_true(self) -> None:
        from swarmline.runtime.types import RuntimeConfig

        cfg = RuntimeConfig(sgr_enabled=True)
        assert cfg.sgr_enabled is True
