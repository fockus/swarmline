"""Native tool-calling + native structured output via the thin runtime (single knob).

The recommended setup: ONE knob — ``structured_mode="auto"`` — gives you provider-native
tool-calling AND provider-native structured output where the provider supports it, with
automatic fallback to portable text-ReAct otherwise. ``use_native_tools`` is an optional
advanced override; ``max_turns`` lifts the react iteration budget.

Runs offline by default via ``swarmline.testing.MockRuntime`` — no API key needed.
Pass ``--live`` with an OpenRouter key in ``OPENAI_API_KEY`` (OpenRouter is OpenAI-compatible)
to drive the real ``thin`` runtime + native tool-calling against gemini-3.1-pro.
"""

from __future__ import annotations

import asyncio
import os
import sys

from pydantic import BaseModel

from swarmline import Agent, AgentConfig
from swarmline.testing import MockRuntime
from swarmline.tools import tool


class Weather(BaseModel):
    """Structured result the model must return."""

    city: str
    summary: str


@tool(
    "get_temperature",
    "Return the current temperature for a given city.",
)
async def get_temperature(city: str) -> str:
    """Return the current temperature for a city (toy tool)."""
    return f'{{"city": "{city}", "celsius": 21}}'


def _build_agent(live: bool) -> Agent:
    if live:
        # Real provider: native tool-calling + native structured output on OpenRouter.
        return Agent(
            AgentConfig(
                system_prompt="You are a concise weather assistant. Use the tool, then answer.",
                model="openrouter:google/gemini-3.1-pro-preview",
                runtime="thin",
                base_url="https://openrouter.ai/api/v1",
                tools=(get_temperature.__tool_definition__,),
                output_type=Weather,
                structured_mode="auto",  # ← the single knob (native where supported, else text-ReAct)
                max_turns=10,            # ← lifts the react iteration budget
            )
        )
    # Offline demo: the SAME config shape, exercised via the mock runtime (no network).
    MockRuntime.register_default()
    return Agent(
        AgentConfig(
            system_prompt="You are a concise weather assistant. Use the tool, then answer.",
            runtime=MockRuntime.NAME,
            model="sonnet",
            tools=(get_temperature.__tool_definition__,),
            structured_mode="auto",
            max_turns=10,
        )
    )


async def main() -> None:
    live = "--live" in sys.argv
    if live and not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY (your OpenRouter key) for --live mode.")

    agent = _build_agent(live)
    if live:
        result = await agent.query_structured(
            "What's the weather in Lisbon? Give a one-line summary.", Weather
        )
        print(f"Structured result: {result}")
    else:
        result = await agent.query("What's the weather in Lisbon?")
        print(f"Mock query result: {result.text}")
        print("Pass --live with OPENAI_API_KEY to run native tools against OpenRouter.")


if __name__ == "__main__":
    asyncio.run(main())
