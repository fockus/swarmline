"""Runtime output collection helpers for subagent/workflow orchestrators.

D10: Extracted from thin_subagent, deepagents_subagent, workflow_executor
to eliminate 3 copies of the same event-handling loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from cognitia.runtime.types import RuntimeEvent


async def collect_runtime_output(
    events: AsyncIterator[RuntimeEvent],
    *,
    error_prefix: str = "",
) -> str:
    """Collect final text from a stream of RuntimeEvents.

    Logic (same across all 3 former call sites):
    - assistant_delta: accumulate text
    - final: use data["text"] as authoritative result
    - error: raise RuntimeError with message

    Args:
        events: Async iterator of RuntimeEvent.
        error_prefix: Optional prefix for error messages (e.g. "ThinRuntime subagent error").

    Returns:
        Final text output.

    Raises:
        RuntimeError: On error events.
    """
    final_text = ""
    async for event in events:
        if event.type == "final":
            final_text = str(event.data.get("text", final_text))
        elif event.type == "assistant_delta":
            final_text += str(event.data.get("text", ""))
        elif event.type == "error":
            raw_message = str(event.data.get("message", "runtime error"))
            if error_prefix:
                message = f"{error_prefix}: {raw_message}"
            else:
                message = raw_message
            raise RuntimeError(message)
    return final_text
