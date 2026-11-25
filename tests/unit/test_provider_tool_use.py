"""Tests for ProviderToolUse and NativeToolCallResult.provider_executed.

Unit tests for the provider-hosted (server-side) tool execution result type
and its additive, backward-compatible wiring onto NativeToolCallResult.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest


class TestProviderToolUse:
    """Tests for ProviderToolUse frozen dataclass."""

    def test_provider_tool_use_defaults(self) -> None:
        from swarmline.runtime.thin.native_tools import ProviderToolUse

        ptu = ProviderToolUse("anthropic", "web_search_20250305")

        assert ptu.provider == "anthropic"
        assert ptu.type == "web_search_20250305"
        assert ptu.name == ""
        assert ptu.input == {}
        assert ptu.summary == ""

    def test_provider_tool_use_is_frozen(self) -> None:
        from swarmline.runtime.thin.native_tools import ProviderToolUse

        ptu = ProviderToolUse("anthropic", "web_search_20250305")

        with pytest.raises(FrozenInstanceError):
            ptu.name = "other"  # type: ignore[misc]


class TestNativeToolCallResultProviderExecuted:
    """Tests for the additive provider_executed field on NativeToolCallResult."""

    def test_native_tool_call_result_provider_executed_defaults_empty(self) -> None:
        """Existing-style positional/keyword construction stays backward compatible."""
        from swarmline.runtime.thin.native_tools import NativeToolCallResult

        result = NativeToolCallResult(
            text="hello", tool_calls=(), stop_reason="end_turn"
        )

        assert result.provider_executed == ()

    def test_native_tool_call_result_carries_provider_executed(self) -> None:
        from swarmline.runtime.thin.native_tools import (
            NativeToolCallResult,
            ProviderToolUse,
        )

        ptu = ProviderToolUse(
            provider="anthropic",
            type="web_search_20250305",
            name="web_search",
            input={"query": "swarmline"},
            summary="3 results found",
        )
        result = NativeToolCallResult(provider_executed=(ptu,))

        assert len(result.provider_executed) == 1
        assert result.provider_executed[0].name == "web_search"
        assert result.provider_executed[0].summary == "3 results found"

    def test_native_tool_call_result_with_usage_preserves_provider_execution(
        self,
    ) -> None:
        from swarmline.runtime.thin.native_tools import (
            NativeToolCallResult,
            ProviderToolUse,
        )

        execution = ProviderToolUse("anthropic", "web_search_20250305")
        usage = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}

        result = NativeToolCallResult(
            "answer", (), "end_turn", (execution,), usage=usage
        )

        assert result.provider_executed == (execution,)
        assert result.usage == usage
