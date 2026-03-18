"""Schemas module."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------


class ToolCallAction(BaseModel):
    """Tool Call Action implementation."""

    name: str = Field(..., description="Полное имя инструмента (mcp__server__tool)")
    args: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = Field(default="")


class FinalAction(BaseModel):
    """Final Action implementation."""

    final_message: str = Field(..., description="Полный ответ пользователю")
    citations: list[str] = Field(default_factory=list)
    next_suggestions: list[str] = Field(default_factory=list)


class ClarifyQuestion(BaseModel):
    """Clarify Question implementation."""

    id: str
    text: str


class ClarifyAction(BaseModel):
    """Clarify Action implementation."""

    questions: list[ClarifyQuestion] = Field(..., min_length=1)
    assistant_message: str = Field(default="")


class ActionEnvelope(BaseModel):
    """Action Envelope implementation."""

    type: str = Field(..., pattern=r"^(tool_call|final|clarify)$")


    tool: ToolCallAction | None = None


    final_message: str | None = None
    citations: list[str] = Field(default_factory=list)
    next_suggestions: list[str] = Field(default_factory=list)


    questions: list[ClarifyQuestion] = Field(default_factory=list)
    assistant_message: str = Field(default="")

    def get_tool_call(self) -> ToolCallAction:
        """Extract tool_call. Raises ValueError if type != tool_call."""
        if self.type != "tool_call" or self.tool is None:
            raise ValueError("ActionEnvelope.type != 'tool_call'")
        return self.tool

    def get_final(self) -> FinalAction:
        """Extract final. Raises ValueError if type != final."""
        if self.type != "final" or self.final_message is None:
            raise ValueError("ActionEnvelope.type != 'final'")
        return FinalAction(
            final_message=self.final_message,
            citations=self.citations,
            next_suggestions=self.next_suggestions,
        )

    def get_clarify(self) -> ClarifyAction:
        """Extract clarify. Raises ValueError if type != clarify."""
        if self.type != "clarify" or not self.questions:
            raise ValueError("ActionEnvelope.type != 'clarify'")
        return ClarifyAction(
            questions=self.questions,
            assistant_message=self.assistant_message,
        )


# ---------------------------------------------------------------------------
# PlanSchema — planner-lite JSON plan
# ---------------------------------------------------------------------------


class PlanStep(BaseModel):
    """Plan Step implementation."""

    id: str
    title: str
    mode: str = Field(default="react", pattern=r"^(conversational|react)$")
    tool_hints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    max_iterations: int = Field(default=4, ge=1, le=20)


class PlanSchema(BaseModel):
    """Plan Schema implementation."""

    type: str = Field(default="plan", pattern=r"^plan$")
    goal: str
    steps: list[PlanStep] = Field(..., min_length=1)
    final_format: str = Field(default="")
