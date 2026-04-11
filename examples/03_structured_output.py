"""Structured output via Pydantic model validation.

Demonstrates: validate_structured_output, extract_pydantic_schema.
No API keys required -- uses a mock LLM response.
"""

import asyncio

from pydantic import BaseModel

from swarmline.runtime.structured_output import (
    extract_pydantic_schema,
    validate_structured_output,
)


class Sentiment(BaseModel):
    label: str
    score: float
    reasoning: str


async def mock_llm_call(prompt: str) -> str:
    """Simulate an LLM returning JSON matching the Sentiment schema."""
    return '{"label": "positive", "score": 0.95, "reasoning": "The text expresses joy."}'


async def main() -> None:
    # 1. Show the JSON Schema that would be sent to the LLM
    schema = extract_pydantic_schema(Sentiment)
    print("Schema for LLM:", schema)

    # 2. Get a mock LLM response and validate it
    raw = await mock_llm_call("Analyze sentiment: I love sunny days!")
    result = validate_structured_output(raw, Sentiment)

    print(f"Parsed: {result}")
    print(f"Label={result.label}, Score={result.score}")

    # 3. Demonstrate validation error handling
    try:
        validate_structured_output('{"label": 123}', Sentiment)
    except Exception as exc:
        print(f"Validation error (expected): {exc}")


if __name__ == "__main__":
    asyncio.run(main())
