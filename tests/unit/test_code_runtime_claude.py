"""Unit tests for ClaudeCodeRuntimeAdapter.

Tests adapter-specific behavior: lazy SDK import, SDK/CLI mode detection,
event mapping, session management. Contract compliance is tested separately
in tests/contract/.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from swarmline.code_runtime_types import (
    CodeRuntimeCapabilities,
    CodeRuntimeConfig,
    CodeRuntimeEvent,
    CodeRuntimeEventType,
    CodeRuntimeSession,
    CodeSessionStatus,
)

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
# 1. Instantiation & Lazy SDK Import
# =====================================================================


class TestInstantiation:
    """Adapter instantiation and SDK detection."""

    def test_create_without_sdk_uses_cli_mode(self) -> None:
        """When anthropic SDK is not installed, adapter falls back to CLI mode."""
        with patch.dict("sys.modules", {"anthropic": None}):
            from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

            adapter = ClaudeCodeRuntimeAdapter()
            caps = adapter.get_capabilities()
            assert caps.mode == "cli"

    def test_create_with_sdk_uses_sdk_mode(self) -> None:
        """When anthropic SDK is available, adapter uses SDK mode."""
        mock_anthropic = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

            adapter = ClaudeCodeRuntimeAdapter()
            caps = adapter.get_capabilities()
            assert caps.mode == "sdk"

    def test_provider_is_claude_code(self) -> None:
        """Provider is always 'claude_code'."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        caps = adapter.get_capabilities()
        assert caps.provider == "claude_code"


# =====================================================================
# 2. Session Management
# =====================================================================


class TestSessionManagement:
    """Session create/terminate lifecycle."""

    async def test_create_session_returns_session_with_correct_provider(self) -> None:
        """create_session returns session with provider from config."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig(
            provider="claude_code", model="claude-sonnet-4-20250514"
        )
        session = await adapter.create_session(config)

        assert isinstance(session, CodeRuntimeSession)
        assert session.provider == "claude_code"
        assert session.status == CodeSessionStatus.CREATED
        assert isinstance(session.capabilities, CodeRuntimeCapabilities)

    async def test_create_session_ids_are_unique(self) -> None:
        """Each session gets a unique ID."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        s1 = await adapter.create_session(config)
        s2 = await adapter.create_session(config)
        assert s1.session_id != s2.session_id

    async def test_terminate_marks_session_terminated(self) -> None:
        """After terminate, the session cannot execute."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)
        await adapter.terminate_session(session.session_id)

        with pytest.raises(RuntimeError, match="terminated"):
            await collect_events(adapter.execute(session.session_id, "test"))

    async def test_terminate_unknown_session_raises(self) -> None:
        """Terminating a non-existent session raises ValueError."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        with pytest.raises(ValueError, match="Unknown session"):
            await adapter.terminate_session("nonexistent-999")

    async def test_execute_unknown_session_raises(self) -> None:
        """Executing on a non-existent session raises ValueError."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        with pytest.raises(ValueError, match="Unknown session"):
            await collect_events(adapter.execute("nonexistent-999", "test"))

    async def test_execute_empty_prompt_raises(self) -> None:
        """Executing with empty prompt raises ValueError."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)

        with pytest.raises(ValueError, match="empty"):
            await collect_events(adapter.execute(session.session_id, ""))

    async def test_execute_whitespace_only_prompt_raises(self) -> None:
        """Whitespace-only prompt also raises."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)

        with pytest.raises(ValueError, match="empty"):
            await collect_events(adapter.execute(session.session_id, "   "))


# =====================================================================
# 3. Event Streaming (CLI fallback mode)
# =====================================================================


class TestEventStreamingCLI:
    """Event streaming when SDK is not available (CLI stub mode)."""

    async def test_execute_yields_status_and_final(self) -> None:
        """In CLI mode, execute yields at least status + final events."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)

        events = await collect_events(
            adapter.execute(session.session_id, "Write hello.py")
        )
        assert len(events) >= 2

        types = [e.type for e in events]
        assert CodeRuntimeEventType.final in types
        assert events[-1].type == CodeRuntimeEventType.final

    async def test_all_events_are_code_runtime_events(self) -> None:
        """All yielded objects are CodeRuntimeEvent instances."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)

        events = await collect_events(adapter.execute(session.session_id, "Write code"))
        for event in events:
            assert isinstance(event, CodeRuntimeEvent)

    async def test_session_reuse_works(self) -> None:
        """A session supports multiple sequential executions."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)

        events_1 = await collect_events(adapter.execute(session.session_id, "First"))
        events_2 = await collect_events(adapter.execute(session.session_id, "Second"))
        assert len(events_1) >= 1
        assert len(events_2) >= 1


# =====================================================================
# 4. Capabilities
# =====================================================================


class TestCapabilities:
    """Capability reporting specifics for Claude adapter."""

    def test_capabilities_has_all_required_flags(self) -> None:
        """All 6 capability flags are queryable."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        caps = adapter.get_capabilities()

        for flag in (
            "approvals",
            "subagents",
            "hooks",
            "worktrees",
            "session_persistence",
            "sandbox",
        ):
            result = caps.supports(flag)
            assert isinstance(result, bool)

    def test_sdk_mode_has_more_capabilities_than_cli(self) -> None:
        """SDK mode enables more flags than CLI mode."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        # CLI mode
        with patch.dict("sys.modules", {"anthropic": None}):
            cli_adapter = ClaudeCodeRuntimeAdapter()
            cli_caps = cli_adapter.get_capabilities()

        # SDK mode
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_sdk}):
            sdk_adapter = ClaudeCodeRuntimeAdapter()
            sdk_caps = sdk_adapter.get_capabilities()

        assert len(sdk_caps.enabled_flags()) >= len(cli_caps.enabled_flags())


# =====================================================================
# 5. Edge-Case Tests (tester-2)
# =====================================================================


class TestClaudeAdapterEdgeCases:
    """Edge-case tests for ClaudeCodeRuntimeAdapter — tester-2."""

    async def test_session_id_has_claude_prefix(self) -> None:
        """All created session IDs start with 'claude-'."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)
        assert session.session_id.startswith("claude-")

    async def test_session_id_length_is_consistent(self) -> None:
        """Session IDs have consistent format: 'claude-' + 12 hex chars."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)

        prefix, hex_part = session.session_id.split("-", 1)
        assert prefix == "claude"
        assert len(hex_part) == 12
        assert all(c in "0123456789abcdef" for c in hex_part)

    async def test_config_sandbox_false_propagates_to_session_capabilities(
        self,
    ) -> None:
        """sandbox=False in config propagates to session capabilities."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig(sandbox=False)
        session = await adapter.create_session(config)

        assert session.capabilities.sandbox is False

    async def test_config_sandbox_true_propagates_to_session_capabilities(self) -> None:
        """sandbox=True in config propagates to session capabilities."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig(sandbox=True)
        session = await adapter.create_session(config)

        assert session.capabilities.sandbox is True

    async def test_session_capabilities_provider_matches_config(self) -> None:
        """Session capabilities.provider echoes config.provider."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig(provider="custom_provider")
        session = await adapter.create_session(config)

        assert session.capabilities.provider == "custom_provider"

    async def test_adapter_level_capabilities_differ_from_session_level(self) -> None:
        """Adapter get_capabilities() uses 'claude_code', session uses config.provider."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig(provider="my_provider")
        session = await adapter.create_session(config)

        adapter_caps = adapter.get_capabilities()
        session_caps = session.capabilities

        assert adapter_caps.provider == "claude_code"
        assert session_caps.provider == "my_provider"

    async def test_double_terminate_does_not_raise(self) -> None:
        """Terminating an already-terminated session does not raise (idempotent)."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)
        await adapter.terminate_session(session.session_id)

        # Session stays in _sessions dict, so second terminate just re-adds to _terminated set
        await adapter.terminate_session(session.session_id)

    async def test_execute_after_terminate_raises_runtime_error_not_value_error(
        self,
    ) -> None:
        """execute after terminate specifically raises RuntimeError, not ValueError."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)
        await adapter.terminate_session(session.session_id)

        with pytest.raises(RuntimeError, match="terminated"):
            await collect_events(adapter.execute(session.session_id, "test"))

    async def test_concurrent_sessions_isolated_terminate(self) -> None:
        """Terminating one session doesn't affect another."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        s1 = await adapter.create_session(config)
        s2 = await adapter.create_session(config)

        await adapter.terminate_session(s1.session_id)

        # s2 still works
        events = await collect_events(adapter.execute(s2.session_id, "Still alive"))
        assert len(events) >= 1

        # s1 is dead
        with pytest.raises(RuntimeError, match="terminated"):
            await collect_events(adapter.execute(s1.session_id, "Should fail"))

    async def test_cli_mode_final_event_has_session_id(self) -> None:
        """CLI stub final event carries the correct session_id."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        with patch.dict("sys.modules", {"anthropic": None}):
            adapter = ClaudeCodeRuntimeAdapter()

        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)
        events = await collect_events(adapter.execute(session.session_id, "Test"))

        final_events = [e for e in events if e.type == CodeRuntimeEventType.final]
        assert len(final_events) == 1
        assert final_events[0].data.get("session_id") == session.session_id

    async def test_cli_mode_delta_truncates_long_prompt(self) -> None:
        """CLI mode delta event truncates prompt to first 50 chars."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        with patch.dict("sys.modules", {"anthropic": None}):
            adapter = ClaudeCodeRuntimeAdapter()

        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)
        long_prompt = "A" * 200
        events = await collect_events(adapter.execute(session.session_id, long_prompt))

        delta_events = [e for e in events if e.type == CodeRuntimeEventType.delta]
        assert len(delta_events) >= 1
        delta_text = delta_events[0].text
        assert "A" * 50 in delta_text
        assert "A" * 200 not in delta_text

    async def test_sdk_mode_yields_tool_events(self) -> None:
        """SDK mode yields tool_use + tool_result events (richer than CLI)."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_sdk}):
            adapter = ClaudeCodeRuntimeAdapter()

        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)
        events = await collect_events(adapter.execute(session.session_id, "Write code"))

        event_types = [e.type for e in events]
        assert CodeRuntimeEventType.tool_use in event_types
        assert CodeRuntimeEventType.tool_result in event_types

    async def test_cli_mode_no_tool_events(self) -> None:
        """CLI mode does NOT yield tool_use or tool_result events."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        with patch.dict("sys.modules", {"anthropic": None}):
            adapter = ClaudeCodeRuntimeAdapter()

        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)
        events = await collect_events(adapter.execute(session.session_id, "Test"))

        event_types = {e.type for e in events}
        assert CodeRuntimeEventType.tool_use not in event_types
        assert CodeRuntimeEventType.tool_result not in event_types

    async def test_created_at_is_utc_datetime(self) -> None:
        """Session created_at is a UTC datetime."""
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        config = CodeRuntimeConfig()
        session = await adapter.create_session(config)

        assert isinstance(session.created_at, datetime)
        assert session.created_at.tzinfo is not None

    def test_isinstance_code_runtime_port(self) -> None:
        """ClaudeCodeRuntimeAdapter satisfies CodeRuntimePort isinstance check."""
        from swarmline.protocols.code_runtime import CodeRuntimePort
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        adapter = ClaudeCodeRuntimeAdapter()
        assert isinstance(adapter, CodeRuntimePort)


class TestDetectSdkAvailable:
    """Unit tests for SDK detection via base adapter."""

    def test_detect_sdk_returns_true_when_importable(self) -> None:
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_sdk}):
            adapter = ClaudeCodeRuntimeAdapter()
            assert adapter._sdk_available is True

    def test_detect_sdk_returns_false_when_not_importable(self) -> None:
        from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter

        with patch.dict("sys.modules", {"anthropic": None}):
            adapter = ClaudeCodeRuntimeAdapter()
            assert adapter._sdk_available is False
