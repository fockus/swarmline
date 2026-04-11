"""Input filters: pre-process messages and system prompts before LLM calls.

Demonstrates: MaxTokensFilter, SystemPromptInjector.
No API keys required.
"""

import asyncio

from swarmline.input_filters import MaxTokensFilter, SystemPromptInjector
from swarmline.runtime.types import Message


async def main() -> None:
    # --- Sample conversation ---
    messages = [
        Message(role="user", content="Hello, I need help with my project."),
        Message(role="assistant", content="Sure! What kind of project are you working on?"),
        Message(role="user", content="It's a web application using Python and FastAPI."),
        Message(role="assistant", content="Great choice! FastAPI is excellent for building APIs."),
        Message(role="user", content="Can you help me design the database schema?"),
    ]
    system_prompt = "You are a senior software engineer."

    # --- 1. MaxTokensFilter -- trim old messages to fit token budget ---
    print("=== MaxTokensFilter ===")
    token_filter = MaxTokensFilter(max_tokens=30, chars_per_token=4.0)
    # With max_tokens=30 (~120 chars), older messages get trimmed
    filtered_msgs, filtered_prompt = await token_filter.filter(messages, system_prompt)
    print(f"Original messages: {len(messages)}")
    print(f"Filtered messages: {len(filtered_msgs)}")
    for m in filtered_msgs:
        print(f"  {m.role}: {m.content[:50]}...")

    # --- 2. SystemPromptInjector -- append/prepend dynamic context ---
    print("\n=== SystemPromptInjector (append) ===")
    injector_append = SystemPromptInjector(
        extra_text="Current date: 2026-03-18. User timezone: UTC+3.",
        position="append",
    )
    _, enriched = await injector_append.filter(messages, system_prompt)
    print(f"Enriched prompt:\n{enriched}")

    print("\n=== SystemPromptInjector (prepend) ===")
    injector_prepend = SystemPromptInjector(
        extra_text="IMPORTANT: Always respond in formal English.",
        position="prepend",
    )
    _, enriched2 = await injector_prepend.filter(messages, system_prompt)
    print(f"Enriched prompt:\n{enriched2}")

    # --- 3. Chaining filters ---
    print("\n=== Chained filters ===")
    filters = [token_filter, injector_append]
    current_msgs, current_prompt = messages, system_prompt
    for f in filters:
        current_msgs, current_prompt = await f.filter(current_msgs, current_prompt)
    print(f"After chain: {len(current_msgs)} messages")
    print(f"Prompt ends with: ...{current_prompt[-60:]}")


if __name__ == "__main__":
    asyncio.run(main())
