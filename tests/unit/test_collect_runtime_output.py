"""Tests for collect_runtime_output helper.

D10: Extracted from thin_subagent, deepagents_subagent, workflow_executor event loops.
"""

from __future__ import annotations

import pytest
from swarmline.runtime.types import RuntimeEvent


async def _async_iter(events: list[RuntimeEvent]):
    for event in events:
        yield event


class TestCollectRuntimeOutput:
    """collect_runtime_output(events) -> str, raises on error."""

    @pytest.mark.asyncio
    async def test_collect_from_final_event(self) -> None:
        from swarmline.orchestration.runtime_helpers import collect_runtime_output

        events = [
            RuntimeEvent.final(text="Final result", new_messages=[]),
        ]
        result = await collect_runtime_output(_async_iter(events))
        assert result == "Final result"

    @pytest.mark.asyncio
    async def test_collect_from_assistant_deltas_without_terminal_raises_runtime_error(
        self,
    ) -> None:
        from swarmline.orchestration.runtime_helpers import collect_runtime_output

        events = [
            RuntimeEvent(type="assistant_delta", data={"text": "Hello "}),
            RuntimeEvent(type="assistant_delta", data={"text": "world"}),
        ]
        with pytest.raises(RuntimeError, match="final RuntimeEvent"):
            await collect_runtime_output(_async_iter(events))

    @pytest.mark.asyncio
    async def test_final_overrides_deltas(self) -> None:
        from swarmline.orchestration.runtime_helpers import collect_runtime_output

        events = [
            RuntimeEvent(type="assistant_delta", data={"text": "partial"}),
            RuntimeEvent.final(text="Authoritative final", new_messages=[]),
        ]
        result = await collect_runtime_output(_async_iter(events))
        assert result == "Authoritative final"

    @pytest.mark.asyncio
    async def test_error_event_raises_runtime_error(self) -> None:
        from swarmline.orchestration.runtime_helpers import collect_runtime_output
        from swarmline.runtime.types import RuntimeErrorData

        events = [
            RuntimeEvent.error(
                RuntimeErrorData(
                    kind="test_error", message="Something broke", recoverable=False
                )
            ),
        ]
        with pytest.raises(RuntimeError, match="Something broke"):
            await collect_runtime_output(_async_iter(events))

    @pytest.mark.asyncio
    async def test_empty_events_return_empty_string(self) -> None:
        from swarmline.orchestration.runtime_helpers import collect_runtime_output

        with pytest.raises(RuntimeError, match="final RuntimeEvent"):
            await collect_runtime_output(_async_iter([]))

    @pytest.mark.asyncio
    async def test_delta_without_terminal_event_raises_runtime_error(self) -> None:
        from swarmline.orchestration.runtime_helpers import collect_runtime_output

        events = [
            RuntimeEvent(type="assistant_delta", data={"text": "partial"}),
        ]

        with pytest.raises(RuntimeError, match="final RuntimeEvent"):
            await collect_runtime_output(_async_iter(events))

    @pytest.mark.asyncio
    async def test_custom_error_message_prefix(self) -> None:
        from swarmline.orchestration.runtime_helpers import collect_runtime_output
        from swarmline.runtime.types import RuntimeErrorData

        events = [
            RuntimeEvent.error(
                RuntimeErrorData(kind="x", message="fail", recoverable=False)
            ),
        ]
        with pytest.raises(RuntimeError, match="Worker error: fail"):
            await collect_runtime_output(
                _async_iter(events), error_prefix="Worker error"
            )
