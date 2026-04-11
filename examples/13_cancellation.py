"""Cooperative cancellation of long-running agent operations.

Demonstrates: CancellationToken with cancel(), is_cancelled, on_cancel().
No API keys required.
"""

import asyncio

from swarmline.runtime.cancellation import CancellationToken


async def simulated_long_task(token: CancellationToken) -> str:
    """A task that checks for cancellation periodically."""
    for step in range(10):
        if token.is_cancelled:
            return f"Cancelled at step {step}"
        print(f"  Step {step}: working...")
        await asyncio.sleep(0.1)
    return "Completed all 10 steps"


async def main() -> None:
    # --- 1. Basic cancellation ---
    print("=== Basic Cancellation ===")
    token = CancellationToken()
    print(f"Initial state: cancelled={token.is_cancelled}")

    token.cancel()
    print(f"After cancel(): cancelled={token.is_cancelled}")

    # Idempotent -- calling cancel() again is safe
    token.cancel()
    print(f"After second cancel(): cancelled={token.is_cancelled}")

    # --- 2. Cancellation callback ---
    print("\n=== Cancellation Callbacks ===")
    token2 = CancellationToken()
    cleanup_done = False

    def on_cancel_cleanup() -> None:
        nonlocal cleanup_done
        cleanup_done = True
        print("  [Callback] Cleanup triggered!")

    token2.on_cancel(on_cancel_cleanup)
    token2.cancel()
    print(f"Cleanup done: {cleanup_done}")

    # --- 3. Cooperative cancellation in async task ---
    print("\n=== Cooperative Cancellation ===")
    token3 = CancellationToken()

    # Cancel after 300ms
    async def cancel_after_delay() -> None:
        await asyncio.sleep(0.3)
        print("  [Timer] Cancelling...")
        token3.cancel()

    cancel_task = asyncio.create_task(cancel_after_delay())
    result = await simulated_long_task(token3)
    await cancel_task
    print(f"Result: {result}")

    # --- 4. Multiple callbacks ---
    print("\n=== Multiple Callbacks ===")
    token4 = CancellationToken()
    events: list[str] = []

    token4.on_cancel(lambda: events.append("cleanup_resources"))
    token4.on_cancel(lambda: events.append("notify_user"))
    token4.on_cancel(lambda: events.append("save_state"))

    token4.cancel()
    print(f"Events fired: {events}")


if __name__ == "__main__":
    asyncio.run(main())
