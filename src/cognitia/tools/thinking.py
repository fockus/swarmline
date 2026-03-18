"""ThinkingTool - CoT + ReAct reasoning for agents.

Standalone tool: the agent calls thinking(thought="...", next_steps=["..."])
for structured reasoning. The result is returned to the LLM context.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from cognitia.runtime.types import ToolSpec

# JSON Schema for the thinking tool
_THINKING_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "thought": {
            "type": "string",
        "description": "Agent reasoning: situation analysis, conclusions, hypotheses.",
        },
        "next_steps": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Next steps the agent plans to take.",
        },
    },
    "required": ["thought", "next_steps"],
}


async def thinking_executor(args: dict) -> str:
    """CoT/ReAct thinking - records reasoning and next steps.

    The agent uses this tool for structured thinking.
    The result is returned to the context as a tool_result.
    """
    thought = args.get("thought", "")
    next_steps = args.get("next_steps")

    if not thought:
        return json.dumps({"status": "error", "message": "thought cannot be empty"})

    if not next_steps or not isinstance(next_steps, list) or len(next_steps) == 0:
        return json.dumps({"status": "error", "message": "next_steps is required (at least 1 step)"})

    return json.dumps(
        {
            "status": "thought_recorded",
            "thought": thought,
            "next_steps": next_steps,
            "instruction": "Continue execution based on this reasoning.",
        }
    )


def create_thinking_tool() -> tuple[ToolSpec, Callable]:
    """Create a ThinkingTool - standalone, with no external dependencies.

    Returns:
        Tuple: (ToolSpec, executor callable).
    """
    spec = ToolSpec(
        name="thinking",
        description=(
            "CoT+ReAct: структурированное рассуждение агента. "
            "Используй для анализа ситуации и планирования следующих шагов."
        ),
        parameters=_THINKING_SCHEMA,
    )
    return spec, thinking_executor
