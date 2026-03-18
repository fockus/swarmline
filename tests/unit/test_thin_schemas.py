"""Tests for Pydantic-shem ThinRuntime - ActionEnvelope, PlanSchema."""

import pytest
from cognitia.runtime.thin.schemas import (
    ActionEnvelope,
    PlanSchema,
    PlanStep,
)
from pydantic import ValidationError


class TestActionEnvelopeToolCall:
    """ActionEnvelope type=tool_call."""

    def test_parse_tool_call(self) -> None:
        data = {
            "type": "tool_call",
            "tool": {
                "name": "mcp__iss__get_bonds",
                "args": {"q": "облигации"},
                "correlation_id": "c1",
            },
        }
        env = ActionEnvelope.model_validate(data)
        assert env.type == "tool_call"
        tc = env.get_tool_call()
        assert tc.name == "mcp__iss__get_bonds"
        assert tc.args == {"q": "облигации"}
        assert tc.correlation_id == "c1"

    def test_tool_call_minimal(self) -> None:
        data = {"type": "tool_call", "tool": {"name": "calc", "args": {}}}
        env = ActionEnvelope.model_validate(data)
        assert env.get_tool_call().name == "calc"

    def test_get_tool_call_wrong_type_raises(self) -> None:
        data = {"type": "final", "final_message": "done"}
        env = ActionEnvelope.model_validate(data)
        with pytest.raises(ValueError, match="tool_call"):
            env.get_tool_call()


class TestActionEnvelopeFinal:
    """ActionEnvelope type=final."""

    def test_parse_final(self) -> None:
        data = {
            "type": "final",
            "final_message": "Ответ пользователю",
            "citations": ["source1"],
            "next_suggestions": ["Что дальше?"],
        }
        env = ActionEnvelope.model_validate(data)
        assert env.type == "final"
        final = env.get_final()
        assert final.final_message == "Ответ пользователю"
        assert final.citations == ["source1"]

    def test_final_minimal(self) -> None:
        data = {"type": "final", "final_message": "ok"}
        env = ActionEnvelope.model_validate(data)
        assert env.get_final().final_message == "ok"

    def test_get_final_wrong_type_raises(self) -> None:
        data = {"type": "tool_call", "tool": {"name": "x", "args": {}}}
        env = ActionEnvelope.model_validate(data)
        with pytest.raises(ValueError, match="final"):
            env.get_final()


class TestActionEnvelopeClarify:
    """ActionEnvelope type=clarify."""

    def test_parse_clarify(self) -> None:
        data = {
            "type": "clarify",
            "questions": [
                {"id": "income", "text": "Какой доход?"},
                {"id": "currency", "text": "Какая валюта?"},
            ],
            "assistant_message": "Уточните",
        }
        env = ActionEnvelope.model_validate(data)
        clarify = env.get_clarify()
        assert len(clarify.questions) == 2
        assert clarify.questions[0].id == "income"

    def test_get_clarify_wrong_type_raises(self) -> None:
        data = {"type": "final", "final_message": "x"}
        env = ActionEnvelope.model_validate(data)
        with pytest.raises(ValueError, match="clarify"):
            env.get_clarify()


class TestActionEnvelopeValidation:
    """Validation ActionEnvelope."""

    def test_invalid_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ActionEnvelope.model_validate({"type": "unknown"})

    def test_missing_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ActionEnvelope.model_validate({"final_message": "x"})


class TestPlanSchema:
    """PlanSchema - planovaya struktura."""

    def test_parse_plan(self) -> None:
        data = {
            "type": "plan",
            "goal": "PF5-диагностика",
            "steps": [
                {"id": "s1", "title": "Собрать данные", "mode": "react"},
                {"id": "s2", "title": "Проанализировать", "mode": "conversational"},
            ],
            "final_format": "PF5: оценка + план",
        }
        plan = PlanSchema.model_validate(data)
        assert plan.goal == "PF5-диагностика"
        assert len(plan.steps) == 2
        assert plan.steps[0].mode == "react"
        assert plan.steps[1].mode == "conversational"

    def test_plan_step_defaults(self) -> None:
        step = PlanStep(id="s1", title="Test")
        assert step.mode == "react"
        assert step.max_iterations == 4
        assert step.tool_hints == []

    def test_plan_empty_steps_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlanSchema.model_validate(
                {
                    "type": "plan",
                    "goal": "x",
                    "steps": [],
                }
            )

    def test_plan_invalid_mode_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlanStep.model_validate(
                {
                    "id": "s1",
                    "title": "x",
                    "mode": "invalid",
                }
            )

    def test_plan_step_with_hints(self) -> None:
        step = PlanStep(
            id="s1",
            title="Найти вклады",
            mode="react",
            tool_hints=["mcp__finuslugi__get_bank_deposits"],
            success_criteria=["Найдены вклады > 10%"],
            max_iterations=6,
        )
        assert step.tool_hints == ["mcp__finuslugi__get_bank_deposits"]
        assert step.max_iterations == 6
