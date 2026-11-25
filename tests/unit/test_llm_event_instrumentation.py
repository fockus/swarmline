"""Unit tests for wrap_with_event_bus -- enriched llm_call_start/end payloads.

Covers correlation_id pairing, duration_ms, error_message on failure, and
the opt-in content capture (config.extra["capture_llm_content"]).
"""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.runtime.thin.runtime_support import wrap_with_event_bus
from swarmline.runtime.types import RuntimeConfig


def _collector(bus: InMemoryEventBus) -> list[tuple[str, dict[str, Any]]]:
    collected: list[tuple[str, dict[str, Any]]] = []
    bus.subscribe("llm_call_start", lambda d: collected.append(("start", d)))
    bus.subscribe("llm_call_end", lambda d: collected.append(("end", d)))
    return collected


async def _echo_llm(
    messages: list[dict[str, str]],
    system_prompt: str,
    *,
    config: RuntimeConfig | None = None,
    **kwargs: Any,
) -> str:
    return "echo-response"


async def _failing_llm(
    messages: list[dict[str, str]],
    system_prompt: str,
    *,
    config: RuntimeConfig | None = None,
    **kwargs: Any,
) -> str:
    raise RuntimeError("provider exploded")


class TestEnrichedLlmEvents:
    async def test_start_and_end_share_correlation_id(self) -> None:
        bus = InMemoryEventBus()
        collected = _collector(bus)
        config = RuntimeConfig(runtime_name="thin", event_bus=bus, model="m1")

        wrapped = wrap_with_event_bus(_echo_llm, config)
        await wrapped([{"role": "user", "content": "hi"}], "sys")

        (_, start), (_, end) = collected
        assert start["correlation_id"]
        assert start["correlation_id"] == end["correlation_id"]
        assert start["model"] == "m1"
        assert isinstance(end["duration_ms"], int)

    async def test_two_calls_get_distinct_correlation_ids(self) -> None:
        bus = InMemoryEventBus()
        collected = _collector(bus)
        config = RuntimeConfig(runtime_name="thin", event_bus=bus, model="m1")

        wrapped = wrap_with_event_bus(_echo_llm, config)
        await wrapped([], "sys")
        await wrapped([], "sys")

        starts = [d for kind, d in collected if kind == "start"]
        assert starts[0]["correlation_id"] != starts[1]["correlation_id"]

    async def test_error_end_event_carries_message_and_flag(self) -> None:
        bus = InMemoryEventBus()
        collected = _collector(bus)
        config = RuntimeConfig(runtime_name="thin", event_bus=bus, model="m1")

        wrapped = wrap_with_event_bus(_failing_llm, config)
        with pytest.raises(RuntimeError):
            await wrapped([], "sys")

        (_, start), (_, end) = collected
        assert end["error"] is True
        assert "provider exploded" in end["error_message"]
        assert end["correlation_id"] == start["correlation_id"]

    async def test_content_not_captured_by_default(self) -> None:
        bus = InMemoryEventBus()
        collected = _collector(bus)
        config = RuntimeConfig(runtime_name="thin", event_bus=bus, model="m1")

        wrapped = wrap_with_event_bus(_echo_llm, config)
        await wrapped([{"role": "user", "content": "secret prompt"}], "sys")

        (_, start), (_, end) = collected
        assert "messages" not in start
        assert "response" not in end

    async def test_content_captured_when_opted_in(self) -> None:
        bus = InMemoryEventBus()
        collected = _collector(bus)
        config = RuntimeConfig(
            runtime_name="thin",
            event_bus=bus,
            model="m1",
            extra={"capture_llm_content": True},
        )

        wrapped = wrap_with_event_bus(_echo_llm, config)
        await wrapped([{"role": "user", "content": "hello"}], "be nice")

        (_, start), (_, end) = collected
        assert start["messages"][0] == {"role": "system", "content": "be nice"}
        assert start["messages"][1] == {"role": "user", "content": "hello"}
        assert end["response"] == "echo-response"

    async def test_captured_content_is_truncated(self) -> None:
        bus = InMemoryEventBus()
        collected = _collector(bus)
        config = RuntimeConfig(
            runtime_name="thin",
            event_bus=bus,
            model="m1",
            extra={"capture_llm_content": True},
        )

        wrapped = wrap_with_event_bus(_echo_llm, config)
        await wrapped([{"role": "user", "content": "x" * 10_000}], "sys")

        (_, start), _ = collected
        assert len(start["messages"][1]["content"]) == 4000
