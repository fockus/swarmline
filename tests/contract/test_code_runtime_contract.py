"""Contract tests for CodeRuntimePort.

Every correct CodeRuntimePort implementation MUST pass all these tests.
Tests assert contract properties (types, field presence, event ordering)
— never implementation details.

Categories:
- Session lifecycle (4 tests)
- Event streaming (4 tests)
- Capability reporting (2 tests)
- Error scenarios (3 tests)
- Edge cases (2 tests)

Total: 15+ tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from swarmline.code_runtime_types import (
    CODE_RUNTIME_ERROR_KINDS,
    CodeRuntimeCapabilities,
    CodeRuntimeConfig,
    CodeRuntimeEvent,
    CodeRuntimeEventType,
    CodeRuntimeSession,
    CodeSessionStatus,
)
from swarmline.protocols.code_runtime import CodeRuntimePort

# =====================================================================
# Helpers
# =====================================================================


async def collect_events(
    stream: AsyncIterator[CodeRuntimeEvent],
) -> list[CodeRuntimeEvent]:
    """Drain an async iterator into a list."""
    events: list[CodeRuntimeEvent] = []
    async for event in stream:
        events.append(event)
    return events


# =====================================================================
# 1. Session Lifecycle (4 tests)
# =====================================================================


class TestSessionLifecycle:
    """Contract: session create/execute/terminate lifecycle."""

    async def test_create_session_returns_valid_session(
        self, adapter: CodeRuntimePort, default_config: CodeRuntimeConfig
    ) -> None:
        """create_session returns a CodeRuntimeSession with required fields."""
        session = await adapter.create_session(default_config)

        assert isinstance(session, CodeRuntimeSession)
        assert isinstance(session.session_id, str)
        assert len(session.session_id) > 0
        assert isinstance(session.provider, str)
        assert isinstance(session.status, CodeSessionStatus)
        assert isinstance(session.capabilities, CodeRuntimeCapabilities)
        assert session.created_at is not None

    async def test_execute_yields_events(
        self, adapter: CodeRuntimePort, default_config: CodeRuntimeConfig
    ) -> None:
        """execute yields at least one event for a valid session."""
        session = await adapter.create_session(default_config)
        events = await collect_events(
            adapter.execute(session.session_id, "Write hello.py")
        )

        assert len(events) >= 1

    async def test_terminate_session_succeeds(
        self, adapter: CodeRuntimePort, default_config: CodeRuntimeConfig
    ) -> None:
        """terminate_session completes without error for an active session."""
        session = await adapter.create_session(default_config)
        await adapter.terminate_session(session.session_id)

    async def test_execute_after_terminate_raises(
        self, adapter: CodeRuntimePort, default_config: CodeRuntimeConfig
    ) -> None:
        """execute on a terminated session raises an error."""
        session = await adapter.create_session(default_config)
        await adapter.terminate_session(session.session_id)

        with pytest.raises(Exception):  # noqa: B017 — contract test, exception type varies by impl
            await collect_events(adapter.execute(session.session_id, "Should fail"))


# =====================================================================
# 2. Event Streaming (4 tests)
# =====================================================================


class TestEventStreaming:
    """Contract: events conform to CodeRuntimeEvent schema."""

    async def test_events_are_code_runtime_event_instances(
        self, adapter: CodeRuntimePort, default_config: CodeRuntimeConfig
    ) -> None:
        """All yielded events are CodeRuntimeEvent instances."""
        session = await adapter.create_session(default_config)
        events = await collect_events(adapter.execute(session.session_id, "Write code"))

        for event in events:
            assert isinstance(event, CodeRuntimeEvent), (
                f"Expected CodeRuntimeEvent, got {type(event).__name__}"
            )

    async def test_event_types_are_valid(
        self, adapter: CodeRuntimePort, default_config: CodeRuntimeConfig
    ) -> None:
        """All event types belong to CodeRuntimeEventType enum."""
        session = await adapter.create_session(default_config)
        events = await collect_events(adapter.execute(session.session_id, "Write code"))

        valid_types = set(CodeRuntimeEventType)
        for event in events:
            assert event.type in valid_types, (
                f"Event type {event.type} not in {valid_types}"
            )

    async def test_final_event_is_last(
        self, adapter: CodeRuntimePort, default_config: CodeRuntimeConfig
    ) -> None:
        """If a 'final' event is present, it is the last event in the stream."""
        session = await adapter.create_session(default_config)
        events = await collect_events(adapter.execute(session.session_id, "Write code"))

        final_indices = [
            i for i, e in enumerate(events) if e.type == CodeRuntimeEventType.final
        ]
        if final_indices:
            assert final_indices[-1] == len(events) - 1, (
                "Final event must be the last event in the stream"
            )

    async def test_error_event_has_valid_kind(
        self, adapter: CodeRuntimePort, default_config: CodeRuntimeConfig
    ) -> None:
        """Error events have a 'kind' field from CODE_RUNTIME_ERROR_KINDS."""
        session = await adapter.create_session(default_config)
        events = await collect_events(adapter.execute(session.session_id, "Write code"))

        error_events = [e for e in events if e.type == CodeRuntimeEventType.error]
        for event in error_events:
            assert "kind" in event.data, "Error event must have a 'kind' field"
            assert event.data["kind"] in CODE_RUNTIME_ERROR_KINDS, (
                f"Error kind '{event.data['kind']}' not in {CODE_RUNTIME_ERROR_KINDS}"
            )


# =====================================================================
# 3. Capability Reporting (2 tests)
# =====================================================================


class TestCapabilityReporting:
    """Contract: capability introspection without session."""

    def test_get_capabilities_without_session(self, adapter: CodeRuntimePort) -> None:
        """get_capabilities returns CodeRuntimeCapabilities without creating a session."""
        caps = adapter.get_capabilities()

        assert isinstance(caps, CodeRuntimeCapabilities)
        assert isinstance(caps.provider, str)
        assert isinstance(caps.mode, str)

    def test_capabilities_has_required_flags(self, adapter: CodeRuntimePort) -> None:
        """Capabilities has all 6 required boolean flags queryable via supports()."""
        caps = adapter.get_capabilities()
        required_flags = {
            "approvals",
            "subagents",
            "hooks",
            "worktrees",
            "session_persistence",
            "sandbox",
        }

        for flag in required_flags:
            result = caps.supports(flag)
            assert isinstance(result, bool), (
                f"supports('{flag}') must return bool, got {type(result).__name__}"
            )


# =====================================================================
# 4. Error Scenarios (3 tests)
# =====================================================================


class TestErrorScenarios:
    """Contract: proper error handling for invalid inputs."""

    async def test_execute_invalid_session_id_raises(
        self, adapter: CodeRuntimePort
    ) -> None:
        """execute with a non-existent session_id raises an error."""
        with pytest.raises(Exception):  # noqa: B017 — contract test, exception type varies by impl
            await collect_events(
                adapter.execute("nonexistent-session-999", "Do something")
            )

    async def test_execute_empty_prompt_raises(
        self, adapter: CodeRuntimePort, default_config: CodeRuntimeConfig
    ) -> None:
        """execute with an empty prompt raises an error."""
        session = await adapter.create_session(default_config)

        with pytest.raises(Exception):  # noqa: B017 — contract test, exception type varies by impl
            await collect_events(adapter.execute(session.session_id, ""))

    async def test_terminate_invalid_session_id_raises(
        self, adapter: CodeRuntimePort
    ) -> None:
        """terminate_session with a non-existent session_id raises an error."""
        with pytest.raises(Exception):  # noqa: B017 — contract test, exception type varies by impl
            await adapter.terminate_session("nonexistent-session-999")


# =====================================================================
# 5. Edge Cases (2 tests)
# =====================================================================


class TestEdgeCases:
    """Contract: session reuse and concurrency."""

    async def test_session_reuse_multiple_executions(
        self, adapter: CodeRuntimePort, default_config: CodeRuntimeConfig
    ) -> None:
        """A single session supports multiple sequential execute calls."""
        session = await adapter.create_session(default_config)

        events_1 = await collect_events(
            adapter.execute(session.session_id, "First task")
        )
        events_2 = await collect_events(
            adapter.execute(session.session_id, "Second task")
        )

        assert len(events_1) >= 1
        assert len(events_2) >= 1

    async def test_concurrent_sessions_isolated(
        self, adapter: CodeRuntimePort, default_config: CodeRuntimeConfig
    ) -> None:
        """Multiple sessions can coexist and operate independently."""
        session_a = await adapter.create_session(default_config)
        session_b = await adapter.create_session(default_config)

        assert session_a.session_id != session_b.session_id

        events_a, events_b = await asyncio.gather(
            collect_events(adapter.execute(session_a.session_id, "Task A")),
            collect_events(adapter.execute(session_b.session_id, "Task B")),
        )

        assert len(events_a) >= 1
        assert len(events_b) >= 1

        await adapter.terminate_session(session_a.session_id)
        await adapter.terminate_session(session_b.session_id)
