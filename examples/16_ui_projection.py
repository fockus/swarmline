"""UI event projection: convert RuntimeEvent streams to frontend-friendly state.

Demonstrates: ChatProjection, UIState, UIMessage, project_stream.
No API keys required.
"""

import asyncio
from collections.abc import AsyncIterator

from swarmline.runtime.types import RuntimeEvent, RuntimeErrorData
from swarmline.ui.projection import ChatProjection, project_stream


async def simulated_agent_stream() -> AsyncIterator[RuntimeEvent]:
    """Simulate a runtime event stream with text, tool calls, and final."""
    yield RuntimeEvent.status("Thinking...")
    yield RuntimeEvent.assistant_delta(text="Let me ")
    yield RuntimeEvent.assistant_delta(text="check the weather. ")

    yield RuntimeEvent.tool_call_started(name="get_weather", args={"city": "Berlin"})
    yield RuntimeEvent.tool_call_finished(
        name="get_weather", correlation_id="tc-1", ok=True, result_summary="22C, sunny"
    )

    yield RuntimeEvent.assistant_delta(text="The weather in Berlin is 22C and sunny!")
    yield RuntimeEvent.final(
        text="Let me check the weather. The weather in Berlin is 22C and sunny!",
        new_messages=[],
    )


async def simulated_error_stream() -> AsyncIterator[RuntimeEvent]:
    """Simulate a stream that ends with an error."""
    yield RuntimeEvent.assistant_delta(text="Processing...")
    yield RuntimeEvent.error(RuntimeErrorData(kind="runtime_crash", message="Connection lost"))


async def main() -> None:
    # 1. Project a successful stream
    print("=== Successful Stream ===")
    projection = ChatProjection()

    async for ui_state in project_stream(simulated_agent_stream(), projection):
        print(f"  Status: {ui_state.status}")
        for msg in ui_state.messages:
            blocks_summary = [
                f"{b.__class__.__name__}({getattr(b, 'text', getattr(b, 'name', ''))[:30]})"
                for b in msg.blocks
            ]
            print(f"  {msg.role}: {blocks_summary}")

    # 2. Final UI state serialization
    print("\n=== Serialized UIState ===")
    final_projection = ChatProjection()
    last_state = None
    async for state in project_stream(simulated_agent_stream(), final_projection):
        last_state = state

    if last_state:
        serialized = last_state.to_dict()
        print(f"  Keys: {list(serialized.keys())}")
        print(f"  Messages: {len(serialized['messages'])}")
        print(f"  Status: {serialized['status']}")

    # 3. Error stream
    print("\n=== Error Stream ===")
    error_projection = ChatProjection()
    async for ui_state in project_stream(simulated_error_stream(), error_projection):
        for msg in ui_state.messages:
            for block in msg.blocks:
                if hasattr(block, "kind") and hasattr(block, "message"):
                    print(f"  Error block: kind={block.kind}, message={block.message}")


if __name__ == "__main__":
    asyncio.run(main())
