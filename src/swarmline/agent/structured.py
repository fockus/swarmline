"""Structured output types and helpers for the Agent facade.

Provides the StructuredOutputError exception and utility functions
for type-safe structured output from LLMs via Pydantic models.

Usage::

    from swarmline.agent import Agent, AgentConfig

    class Sentiment(BaseModel):
        label: str
        score: float

    agent = Agent(AgentConfig(system_prompt="Analyze sentiment", runtime="thin"))
    result = await agent.query_structured("I love sunny days!", Sentiment)
    print(result.label, result.score)
"""

from __future__ import annotations


class StructuredOutputError(Exception):
    """Raised when structured output validation fails after all retries.

    Attributes
    ----------
    raw_text:
        The raw LLM response text that failed validation.
    output_type_name:
        Name of the expected Pydantic model type.
    """

    def __init__(self, message: str, *, raw_text: str = "", output_type_name: str = "") -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.output_type_name = output_type_name
