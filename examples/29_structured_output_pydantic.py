#!/usr/bin/env python3
"""Example: Type-safe structured output with Pydantic models.

Demonstrates Agent.query_structured() — returns validated Pydantic models
instead of raw text. Includes automatic retry on validation errors.

No API keys required — uses a mock LLM response.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import BaseModel, Field

from swarmline.agent import Agent, AgentConfig, StructuredOutputError


# ---------------------------------------------------------------------------
# 1. Define your output schema as a Pydantic model
# ---------------------------------------------------------------------------


class SentimentAnalysis(BaseModel):
    """Sentiment analysis result."""

    label: str = Field(description="Sentiment label: positive, negative, or neutral")
    score: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
    reasoning: str = Field(description="Brief explanation of the sentiment")


class ExtractedEntities(BaseModel):
    """Named entities extracted from text."""

    people: list[str] = Field(default_factory=list, description="Person names")
    places: list[str] = Field(default_factory=list, description="Location names")
    organizations: list[str] = Field(default_factory=list, description="Organization names")


# ---------------------------------------------------------------------------
# 2. Mock LLM for offline demo
# ---------------------------------------------------------------------------


_MOCK_RESPONSES: dict[str, str] = {
    "sentiment": json.dumps({
        "label": "positive",
        "score": 0.92,
        "reasoning": "The text expresses strong enthusiasm and joy about the weather.",
    }),
    "entities": json.dumps({
        "people": ["Alice", "Bob"],
        "places": ["Paris", "Tokyo"],
        "organizations": ["Swarmline Labs", "ACME Corp"],
    }),
}


async def mock_llm(messages: list[dict[str, str]], system_prompt: str, **kw: Any) -> str:
    """Simulate an LLM returning structured JSON."""
    prompt = messages[-1]["content"].lower() if messages else ""
    if "entit" in prompt:
        response = _MOCK_RESPONSES["entities"]
    else:
        response = _MOCK_RESPONSES["sentiment"]
    return json.dumps({"type": "final", "final_message": response})


# ---------------------------------------------------------------------------
# 3. Use Agent.query_structured()
# ---------------------------------------------------------------------------


async def main() -> None:
    from unittest.mock import patch

    from swarmline.runtime.thin.runtime import ThinRuntime

    def patched_create(self: Any, config: Any, **kwargs: Any) -> ThinRuntime:
        return ThinRuntime(config=config, llm_call=mock_llm)

    with patch("swarmline.runtime.factory.RuntimeFactory.create", patched_create):
        agent = Agent(AgentConfig(
            system_prompt="You are a helpful analysis assistant.",
            runtime="thin",
        ))

        # --- Sentiment Analysis ---
        print("=== Sentiment Analysis ===")
        sentiment = await agent.query_structured(
            "Analyze: I absolutely love sunny days! They make me so happy!",
            SentimentAnalysis,
        )
        print(f"  Label: {sentiment.label}")
        print(f"  Score: {sentiment.score:.2f}")
        print(f"  Reasoning: {sentiment.reasoning}")
        print(f"  Type: {type(sentiment).__name__}")
        print()

        # --- Entity Extraction ---
        print("=== Entity Extraction ===")
        entities = await agent.query_structured(
            "Extract entities: Alice met Bob in Paris near the Swarmline Labs office.",
            ExtractedEntities,
        )
        print(f"  People: {entities.people}")
        print(f"  Places: {entities.places}")
        print(f"  Organizations: {entities.organizations}")
        print(f"  Type: {type(entities).__name__}")
        print()

        # --- Error Handling ---
        print("=== Error Handling ===")
        try:
            # This will fail after retries (LLM returns sentiment, not entities)
            await agent.query_structured("Gimme something", SentimentAnalysis)
            print("  Success (mock always returns valid data)")
        except StructuredOutputError as exc:
            print(f"  StructuredOutputError: {exc}")

        print("\nAll examples completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
