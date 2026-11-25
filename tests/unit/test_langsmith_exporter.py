"""Unit tests for LangSmithExporter -- EventBus to LangSmith runs bridge.

Uses a duck-typed fake LangSmith client (create_run / update_run surface).
The real langsmith package is NOT required.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest

from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.observability.langsmith_exporter import LangSmithExporter


class FakeLangSmithClient:
    """Duck-typed stand-in for langsmith.Client."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[uuid.UUID, dict[str, Any]]] = []

    def create_run(self, **kwargs: Any) -> None:
        self.created.append(kwargs)

    def update_run(self, run_id: uuid.UUID, **kwargs: Any) -> None:
        self.updated.append((run_id, kwargs))


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def client() -> FakeLangSmithClient:
    return FakeLangSmithClient()


class TestLangSmithLlmCalls:
    """LLM call events create and close LangSmith llm runs."""

    async def test_llm_start_end_creates_and_updates_run(
        self, event_bus: InMemoryEventBus, client: FakeLangSmithClient
    ) -> None:
        exporter = LangSmithExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )
        await event_bus.emit(
            "llm_call_end", {"model": "sonnet", "correlation_id": "c1"}
        )

        exporter.detach()

        assert len(client.created) == 1
        run = client.created[0]
        assert run["name"] == "swarmline.llm.sonnet"
        assert run["run_type"] == "llm"
        assert run["inputs"]["model"] == "sonnet"
        assert len(client.updated) == 1
        run_id, update = client.updated[0]
        assert run_id == run["id"]
        assert "end_time" in update

    async def test_root_run_has_trace_id_and_dotted_order(
        self, event_bus: InMemoryEventBus, client: FakeLangSmithClient
    ) -> None:
        exporter = LangSmithExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )

        run = client.created[0]
        assert run["trace_id"] == run["id"]
        assert run["dotted_order"].endswith(str(run["id"]))

    async def test_tokens_and_response_land_in_outputs(
        self, event_bus: InMemoryEventBus, client: FakeLangSmithClient
    ) -> None:
        exporter = LangSmithExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )
        await event_bus.emit(
            "llm_call_end",
            {
                "model": "sonnet",
                "correlation_id": "c1",
                "response": "hello",
                "input_tokens": 10,
                "output_tokens": 5,
            },
        )

        _, update = client.updated[0]
        assert update["outputs"] == {
            "response": "hello",
            "input_tokens": 10,
            "output_tokens": 5,
        }

    async def test_error_marks_run_failed(
        self, event_bus: InMemoryEventBus, client: FakeLangSmithClient
    ) -> None:
        exporter = LangSmithExporter(event_bus, client=client)
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

        _, update = client.updated[0]
        assert update["error"] == "rate limit"

    async def test_concurrent_calls_paired_by_correlation_id(
        self, event_bus: InMemoryEventBus, client: FakeLangSmithClient
    ) -> None:
        exporter = LangSmithExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit("llm_call_start", {"model": "a", "correlation_id": "a1"})
        await event_bus.emit("llm_call_start", {"model": "b", "correlation_id": "b1"})
        await event_bus.emit(
            "llm_call_end",
            {"model": "b", "correlation_id": "b1", "response": "from-b"},
        )
        await event_bus.emit(
            "llm_call_end",
            {"model": "a", "correlation_id": "a1", "response": "from-a"},
        )

        run_ids = {r["inputs"]["model"]: r["id"] for r in client.created}
        updates = dict(client.updated)
        assert updates[run_ids["a"]]["outputs"]["response"] == "from-a"
        assert updates[run_ids["b"]]["outputs"]["response"] == "from-b"

    async def test_end_without_start_is_noop(
        self, event_bus: InMemoryEventBus, client: FakeLangSmithClient
    ) -> None:
        exporter = LangSmithExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit("llm_call_end", {"model": "sonnet"})

        assert client.updated == []


class TestLangSmithToolCalls:
    """Tool call events create tool runs."""

    async def test_tool_call_creates_tool_run(
        self, event_bus: InMemoryEventBus, client: FakeLangSmithClient
    ) -> None:
        exporter = LangSmithExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit(
            "tool_call_start", {"name": "web_search", "correlation_id": "t1"}
        )
        await event_bus.emit(
            "tool_call_end", {"name": "web_search", "correlation_id": "t1", "ok": True}
        )

        run = client.created[0]
        assert run["name"] == "swarmline.tool.web_search"
        assert run["run_type"] == "tool"
        _, update = client.updated[0]
        assert update["outputs"] == {"ok": True}

    async def test_tool_error_marks_run_failed(
        self, event_bus: InMemoryEventBus, client: FakeLangSmithClient
    ) -> None:
        exporter = LangSmithExporter(event_bus, client=client)
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

        _, update = client.updated[0]
        assert update["error"] == "timeout"


class TestLangSmithMetadataAndLifecycle:
    """Metadata, project, detach cleanup, and resilience."""

    async def test_project_and_metadata_propagate(
        self, event_bus: InMemoryEventBus, client: FakeLangSmithClient
    ) -> None:
        exporter = LangSmithExporter(
            event_bus,
            client=client,
            project_name="my-agent",
            runtime_name="thin",
            session_id="s1",
        )
        exporter.attach()

        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )

        run = client.created[0]
        assert run["project_name"] == "my-agent"
        meta = run["extra"]["metadata"]
        assert meta["swarmline.runtime"] == "thin"
        assert meta["swarmline.session_id"] == "s1"

    async def test_detach_closes_lingering_runs(
        self, event_bus: InMemoryEventBus, client: FakeLangSmithClient
    ) -> None:
        exporter = LangSmithExporter(event_bus, client=client)
        exporter.attach()

        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )
        exporter.detach()

        assert len(client.updated) == 1
        _, update = client.updated[0]
        assert "end_time" in update

    async def test_client_errors_do_not_propagate(
        self, event_bus: InMemoryEventBus
    ) -> None:
        class BrokenClient:
            def create_run(self, **kwargs: Any) -> None:
                raise RuntimeError("network down")

            def update_run(self, run_id: uuid.UUID, **kwargs: Any) -> None:
                raise RuntimeError("network down")

        exporter = LangSmithExporter(event_bus, client=BrokenClient())
        exporter.attach()

        await event_bus.emit(
            "llm_call_start", {"model": "sonnet", "correlation_id": "c1"}
        )
        await event_bus.emit(
            "tool_call_start", {"name": "calc", "correlation_id": "t1"}
        )
        exporter.detach()


class TestLangSmithImportGuard:
    """Missing langsmith raises a helpful ImportError."""

    def test_missing_langsmith_gives_clear_error(self) -> None:
        with patch.dict("sys.modules", {"langsmith": None}):
            from swarmline.observability.langsmith_exporter import (
                _try_import_langsmith,
            )

            with pytest.raises(ImportError, match="(?i)langsmith"):
                _try_import_langsmith()
