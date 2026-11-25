"""NextStep schema and SGR (Structured Generation + Reasoning) output parser."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from swarmline.runtime.thin.parsers import strip_markdown_fences


class NextStep(BaseModel, frozen=True):
    """Structured next-step decision produced by SGR-enabled agents.

    Represents a single reasoning snapshot: what the agent sees, its plan,
    available options, reasoning, chosen action, and confidence level.
    """

    current_state: str
    plan: list[str]
    options: list[str]
    reasoning: str
    action: str
    confidence: float = Field(ge=0.0, le=1.0)


def parse_nextstep(text: str) -> NextStep | None:
    """Parse NextStep from LLM output text.

    Tolerant of markdown fences and surrounding prose.
    Returns None on any parse/validation failure.
    """
    if not text or not text.strip():
        return None

    cleaned = strip_markdown_fences(text).strip()
    if not cleaned:
        return None

    try:
        json.loads(cleaned)
    except json.JSONDecodeError:
        # Try extracting JSON from surrounding text
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        cleaned = cleaned[start : end + 1]
        try:
            json.loads(cleaned)
        except json.JSONDecodeError:
            return None

    try:
        return NextStep.model_validate_json(cleaned)
    except Exception:
        return None


def nextstep_system_instruction() -> str:
    """Return the system prompt instruction block for SGR NextStep output.

    Tells the LLM to produce structured JSON matching the NextStep schema.
    """
    schema = NextStep.model_json_schema()
    schema_json = json.dumps(schema, indent=2, ensure_ascii=False)
    return (
        "## SGR NextStep Output\n"
        "You MUST respond with a single JSON object matching the schema below.\n"
        "No markdown wrapping, no explanations outside the JSON.\n\n"
        "Fields:\n"
        "- current_state: brief description of what you observe right now\n"
        "- plan: ordered list of steps you intend to take\n"
        "- options: alternative actions you considered\n"
        "- reasoning: why you chose this action over alternatives\n"
        "- action: the concrete action you will take next\n"
        "- confidence: float 0.0-1.0 indicating how confident you are\n\n"
        f"Schema:\n{schema_json}"
    )
