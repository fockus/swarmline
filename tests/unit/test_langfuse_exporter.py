"""Unit tests for LangfuseExporter -- EventBus to Langfuse observations bridge.

Uses a duck-typed fake Langfuse client (matching the SDK v3 surface the
exporter relies on: start_generation / start_span / flush, observations
with update / end). The real langfuse package is NOT required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.observability.langfuse_exporter import LangfuseExporter


class FakeObservation:
    """Records update/end calls like a Langfuse span/generation."""

    def __init__(self, kind: str, kwargs: dict[str, Any]) -> None:
        self.kind = kind
        self.kwargs = kwargs
        self.updates: list[dict[str, Any]] = []
        self.ended = False

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)

    def end(self) -> None:
        self.ended = True


class FakeLangfuseClient:
    """Duck-typed stand-in for langfuse.Langfuse (v3 surface)."""

    def __init__(self) -> None:
        self.observations: list[FakeObservation] = []
        self.flushed = False

    def start_generation(self, **kwargs: Any) -> FakeObservation:
        obs = FakeObservation("generation", kwargs)
        self.observations.append(obs)
        return obs

    def start_span(self, **kwargs: Any) -> FakeObservation:
        obs = FakeObservation("span", kwargs)
        self.observations.append(obs)
        return obs

    def flush(self) -> None:
        self.flushed = True


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def client() -> FakeLangfuseClient:
    return FakeLangfuseClient()


class TestLangfuseLlmCalls:
    """LLM call events create Langfuse generations."""

    async def test_llm_start_end_creates_ended_generation(
        self, event_bus: InMemoryEventBus, client: FakeLangfuseClient
    ) -> None:
        exporter = LangfuseExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )
        await event_bus.emit(
            "llm_call_end", {"model": "sonnet", "correlation_id": "c1"}
        )

        exporter.detach()

        assert len(client.observations) == 1
        obs = client.observations[0]
        assert obs.kind == "generation"
        assert obs.kwargs["name"] == "swarmline.llm.sonnet"
        assert obs.kwargs["model"] == "sonnet"
        assert obs.ended

    async def test_token_usage_recorded_as_usage_details(
        self, event_bus: InMemoryEventBus, client: FakeLangfuseClient
    ) -> None:
        exporter = LangfuseExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )
        await event_bus.emit(
            "llm_call_end",
            {
                "model": "sonnet",
                "correlation_id": "c1",
                "input_tokens": 150,
                "output_tokens": 42,
            },
        )

        obs = client.observations[0]
        assert obs.updates == [{"usage_details": {"input": 150, "output": 42}}]

    async def test_captured_content_flows_to_input_and_output(
        self, event_bus: InMemoryEventBus, client: FakeLangfuseClient
    ) -> None:
        exporter = LangfuseExporter(event_bus, client=client)
        exporter.attach()

        messages = [{"role": "user", "content": "hi"}]
        await event_bus.emit(
            "llm_call_start",
            {"model": "sonnet", "correlation_id": "c1", "messages": messages},
        )
        await event_bus.emit(
            "llm_call_end",
            {"model": "sonnet", "correlation_id": "c1", "response": "hello"},
        )

        obs = client.observations[0]
        assert obs.kwargs["input"] == messages
        assert obs.updates[0]["output"] == "hello"

    async def test_error_sets_error_level(
        self, event_bus: InMemoryEventBus, client: FakeLangfuseClient
    ) -> None:
        exporter = LangfuseExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )
        await event_bus.emit(
            "llm_call_end",
            {
                "model": "sonnet",
                "correlation_id": "c1",
                "error": True,
                "error_message": "rate limit",
            },
        )

        obs = client.observations[0]
        assert obs.updates[0]["level"] == "ERROR"
        assert obs.updates[0]["status_message"] == "rate limit"
        assert obs.ended

    async def test_concurrent_llm_calls_paired_by_correlation_id(
        self, event_bus: InMemoryEventBus, client: FakeLangfuseClient
    ) -> None:
        exporter = LangfuseExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit("llm_call_start", {"model": "a", "correlation_id": "a1"})
        await event_bus.emit("llm_call_start", {"model": "b", "correlation_id": "b1"})
        # End in reverse order with distinct usage
        await event_bus.emit(
            "llm_call_end",
            {"model": "b", "correlation_id": "b1", "input_tokens": 2},
        )
        await event_bus.emit(
            "llm_call_end",
            {"model": "a", "correlation_id": "a1", "input_tokens": 1},
        )

        by_model = {o.kwargs["model"]: o for o in client.observations}
        assert by_model["a"].updates[0]["usage_details"]["input"] == 1
        assert by_model["b"].updates[0]["usage_details"]["input"] == 2

    async def test_end_without_start_is_noop(
        self, event_bus: InMemoryEventBus, client: FakeLangfuseClient
    ) -> None:
        exporter = LangfuseExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit("llm_call_end", {"model": "sonnet"})

        assert client.observations == []


class TestLangfuseToolCalls:
    """Tool call events create Langfuse spans."""

    async def test_tool_call_creates_ended_span(
        self, event_bus: InMemoryEventBus, client: FakeLangfuseClient
    ) -> None:
        exporter = LangfuseExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit(
            "tool_call_start", {"name": "web_search", "correlation_id": "t1"}
        )
        await event_bus.emit(
            "tool_call_end", {"name": "web_search", "correlation_id": "t1"}
        )

        assert len(client.observations) == 1
        obs = client.observations[0]
        assert obs.kind == "span"
        assert obs.kwargs["name"] == "swarmline.tool.web_search"
        assert obs.ended

    async def test_tool_error_sets_error_level(
        self, event_bus: InMemoryEventBus, client: FakeLangfuseClient
    ) -> None:
        exporter = LangfuseExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit(
            "tool_call_start", {"name": "sandbox", "correlation_id": "t1"}
        )
        await event_bus.emit(
            "tool_call_end",
            {
                "name": "sandbox",
                "correlation_id": "t1",
                "error": True,
                "error_message": "timeout",
            },
        )

        obs = client.observations[0]
        assert obs.updates[0]["level"] == "ERROR"
        assert obs.updates[0]["status_message"] == "timeout"


class TestLangfuseMetadataAndLifecycle:
    """Constructor metadata, detach cleanup, and resilience."""

    async def test_runtime_and_session_metadata(
        self, event_bus: InMemoryEventBus, client: FakeLangfuseClient
    ) -> None:
        exporter = LangfuseExporter(
            event_bus, client=client, runtime_name="thin", session_id="s1"
        )
        exporter.attach()

        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )

        meta = client.observations[0].kwargs["metadata"]
        assert meta["swarmline.runtime"] == "thin"
        assert meta["swarmline.session_id"] == "s1"

    async def test_detach_ends_lingering_observations_and_flushes(
        self, event_bus: InMemoryEventBus, client: FakeLangfuseClient
    ) -> None:
        exporter = LangfuseExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )
        exporter.detach()

        assert client.observations[0].ended
        assert client.flushed

    async def test_detach_stops_new_observations(
        self, event_bus: InMemoryEventBus, client: FakeLangfuseClient
    ) -> None:
        exporter = LangfuseExporter(event_bus, client=client)
        exporter.attach()
        exporter.detach()

        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )

        assert client.observations == []

    async def test_client_errors_do_not_propagate(
        self, event_bus: InMemoryEventBus
    ) -> None:
        class BrokenClient:
            def start_generation(self, **kwargs: Any) -> Any:
                raise RuntimeError("network down")

            def start_span(self, **kwargs: Any) -> Any:
                raise RuntimeError("network down")

            def flush(self) -> None:
                raise RuntimeError("network down")

        exporter = LangfuseExporter(event_bus, client=BrokenClient())
        exporter.attach()

        # Handlers swallow exporter errors; the emit itself must not raise.
        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )
        await event_bus.emit(
            "tool_call_start", {"name": "calc", "correlation_id": "t1"}
        )
        exporter.detach()


class TestLangfuseImportGuard:
    """Missing langfuse raises a helpful ImportError."""

    def test_missing_langfuse_gives_clear_error(self) -> None:
        with patch.dict("sys.modules", {"langfuse": None}):
            from swarmline.observability.langfuse_exporter import _try_import_langfuse

            with pytest.raises(ImportError, match="(?i)langfuse"):
                _try_import_langfuse()
