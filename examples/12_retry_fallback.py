"""Retry policies, model fallback chains, and circuit breaker.

Demonstrates: ExponentialBackoff, ModelFallbackChain, ProviderFallback, CircuitBreaker.
No API keys required.
"""

import asyncio

from swarmline.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry
from swarmline.retry import ExponentialBackoff, ModelFallbackChain, ProviderFallback


async def main() -> None:
    # --- 1. Exponential backoff with jitter ---
    print("=== Exponential Backoff ===")
    backoff = ExponentialBackoff(max_retries=3, base_delay=1.0, max_delay=30.0, jitter=True)

    error = TimeoutError("API timeout")
    for attempt in range(5):
        should, delay = backoff.should_retry(error, attempt)
        print(f"Attempt {attempt}: retry={should}, delay={delay:.2f}s")

    # --- 2. Model fallback chain ---
    print("\n=== Model Fallback Chain ===")
    chain = ModelFallbackChain(models=["gpt-4o", "claude-sonnet", "gemini-pro"])

    current = "gpt-4o"
    while current:
        print(f"Current model: {current}")
        next_model = chain.next_model(current)
        if next_model is None:
            print("No more fallbacks available.")
            break
        current = next_model

    # --- 3. Provider fallback ---
    print("\n=== Provider Fallback ===")
    fallback = ProviderFallback(fallback_model="openai:gpt-4o")
    print(f"Provider fallback target: {fallback.fallback_model}")

    # --- 4. Circuit breaker ---
    print("\n=== Circuit Breaker ===")
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=1.0)
    print(f"Initial state: {cb.state.value}")

    # Simulate failures
    for i in range(4):
        if cb.allow_request():
            cb.record_failure()
            print(f"  Failure #{i + 1}: state={cb.state.value}")
        else:
            print(f"  Request #{i + 1} blocked: state={cb.state.value}")

    # After cooldown, circuit moves to HALF_OPEN
    print(f"Circuit is OPEN, requests blocked: allow={cb.allow_request()}")

    # --- 5. Circuit breaker registry (per-service) ---
    print("\n=== Circuit Breaker Registry ===")
    registry = CircuitBreakerRegistry(failure_threshold=2, cooldown_seconds=5.0)
    api_cb = registry.get("openai-api")
    db_cb = registry.get("postgres-db")
    print(f"OpenAI CB state: {api_cb.state.value}")
    print(f"Postgres CB state: {db_cb.state.value}")

    # Same key returns same breaker
    assert registry.get("openai-api") is api_cb
    print("Registry returns same instance for same key: OK")


if __name__ == "__main__":
    asyncio.run(main())
