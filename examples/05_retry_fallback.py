"""Retry and fallback policies for LLM calls.

Demonstrates: ExponentialBackoff, ModelFallbackChain, ProviderFallback.
No API keys required.
"""

import asyncio

from cognitia.retry import ExponentialBackoff, ModelFallbackChain, ProviderFallback


async def main() -> None:
    # 1. Exponential backoff with jitter
    backoff = ExponentialBackoff(max_retries=3, base_delay=1.0, max_delay=30.0, jitter=True)

    error = TimeoutError("API timeout")
    for attempt in range(5):
        should, delay = backoff.should_retry(error, attempt)
        print(f"Attempt {attempt}: retry={should}, delay={delay:.2f}s")

    # 2. Model fallback chain
    chain = ModelFallbackChain(models=["gpt-4o", "claude-sonnet", "gemini-pro"])

    current = "gpt-4o"
    while current:
        print(f"Current model: {current}")
        next_model = chain.next_model(current)
        if next_model is None:
            print("No more fallbacks available.")
            break
        current = next_model

    # 3. Provider fallback
    fallback = ProviderFallback(fallback_model="openai:gpt-4o")
    print(f"Provider fallback target: {fallback.fallback_model}")


if __name__ == "__main__":
    asyncio.run(main())
