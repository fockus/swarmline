"""Unit tests for InputFilter protocol and builtin filters."""

from __future__ import annotations

import pytest

from swarmline.input_filters import InputFilter, MaxTokensFilter, SystemPromptInjector
from swarmline.runtime.types import Message, RuntimeConfig


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class _NoopFilter:
    """Dummy filter implementing InputFilter protocol."""

    async def filter(
        self, messages: list[Message], system_prompt: str
    ) -> tuple[list[Message], str]:
        return messages, system_prompt


class TestInputFilterProtocol:
    def test_protocol_compliance_noop(self) -> None:
        """_NoopFilter satisfies InputFilter protocol at runtime."""
        f = _NoopFilter()
        assert isinstance(f, InputFilter)

    def test_protocol_compliance_max_tokens(self) -> None:
        f = MaxTokensFilter(max_tokens=100)
        assert isinstance(f, InputFilter)

    def test_protocol_compliance_injector(self) -> None:
        f = SystemPromptInjector(extra_text="x")
        assert isinstance(f, InputFilter)


# ---------------------------------------------------------------------------
# MaxTokensFilter
# ---------------------------------------------------------------------------


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


class TestMaxTokensFilter:
    @pytest.mark.asyncio
    async def test_within_limit_passes_unchanged(self) -> None:
        msgs = [_msg("user", "hello")]
        f = MaxTokensFilter(max_tokens=1000)
        result_msgs, result_prompt = await f.filter(msgs, "sys")
        assert result_msgs == msgs
        assert result_prompt == "sys"

    @pytest.mark.asyncio
    async def test_trims_oldest_messages_when_over_limit(self) -> None:
        """When total exceeds budget, oldest non-system messages are dropped."""
        # Each char ~ 0.25 tokens (default chars_per_token=4.0)
        # 400 chars = 100 tokens. Budget = 120 tokens.
        # system_prompt = 40 chars = 10 tokens
        # 3 messages x 400 chars = 300 tokens total = 310 with system
        # Budget 120 -> should keep only newest message(s)
        msgs = [
            _msg("user", "a" * 400),
            _msg("assistant", "b" * 400),
            _msg("user", "c" * 400),
        ]
        f = MaxTokensFilter(max_tokens=120, chars_per_token=4.0)
        result_msgs, result_prompt = await f.filter(msgs, "x" * 40)
        # Should have dropped oldest messages, keeping newest
        assert len(result_msgs) < len(msgs)
        # Last message always preserved
        assert result_msgs[-1] == msgs[-1]

    @pytest.mark.asyncio
    async def test_preserves_system_prompt(self) -> None:
        """System prompt is never truncated."""
        msgs = [_msg("user", "hello")]
        prompt = "important system prompt " * 100
        f = MaxTokensFilter(max_tokens=50, chars_per_token=4.0)
        result_msgs, result_prompt = await f.filter(msgs, prompt)
        assert result_prompt == prompt

    @pytest.mark.asyncio
    async def test_empty_messages_returns_empty(self) -> None:
        f = MaxTokensFilter(max_tokens=100)
        result_msgs, result_prompt = await f.filter([], "sys")
        assert result_msgs == []
        assert result_prompt == "sys"

    @pytest.mark.asyncio
    async def test_single_message_never_dropped(self) -> None:
        """Even if single message exceeds budget, it is preserved."""
        msgs = [_msg("user", "x" * 10000)]
        f = MaxTokensFilter(max_tokens=10, chars_per_token=4.0)
        result_msgs, _ = await f.filter(msgs, "")
        assert len(result_msgs) == 1
        assert result_msgs[0] == msgs[0]

    @pytest.mark.asyncio
    async def test_custom_chars_per_token(self) -> None:
        """chars_per_token=2.0 means each char ~ 0.5 tokens."""
        # 100 chars = 50 tokens with cpt=2.0
        msgs = [
            _msg("user", "a" * 100),
            _msg("user", "b" * 100),
        ]
        # Budget = 60 tokens. System = 0. Two msgs = 100 tokens. Should trim.
        f = MaxTokensFilter(max_tokens=60, chars_per_token=2.0)
        result_msgs, _ = await f.filter(msgs, "")
        assert len(result_msgs) == 1
        assert result_msgs[0] == msgs[-1]


# ---------------------------------------------------------------------------
# SystemPromptInjector
# ---------------------------------------------------------------------------


class TestSystemPromptInjector:
    @pytest.mark.asyncio
    async def test_append_mode(self) -> None:
        f = SystemPromptInjector(extra_text="EXTRA", position="append")
        msgs = [_msg("user", "hi")]
        result_msgs, result_prompt = await f.filter(msgs, "BASE")
        assert result_prompt == "BASE\nEXTRA"
        assert result_msgs == msgs

    @pytest.mark.asyncio
    async def test_prepend_mode(self) -> None:
        f = SystemPromptInjector(extra_text="EXTRA", position="prepend")
        _, result_prompt = await f.filter([], "BASE")
        assert result_prompt == "EXTRA\nBASE"

    @pytest.mark.asyncio
    async def test_default_position_is_append(self) -> None:
        f = SystemPromptInjector(extra_text="EXTRA")
        _, result_prompt = await f.filter([], "BASE")
        assert result_prompt == "BASE\nEXTRA"

    @pytest.mark.asyncio
    async def test_empty_system_prompt_append(self) -> None:
        f = SystemPromptInjector(extra_text="EXTRA", position="append")
        _, result_prompt = await f.filter([], "")
        assert result_prompt == "EXTRA"

    @pytest.mark.asyncio
    async def test_empty_system_prompt_prepend(self) -> None:
        f = SystemPromptInjector(extra_text="EXTRA", position="prepend")
        _, result_prompt = await f.filter([], "")
        assert result_prompt == "EXTRA"


# ---------------------------------------------------------------------------
# Filter chain
# ---------------------------------------------------------------------------


class TestFilterChain:
    @pytest.mark.asyncio
    async def test_multiple_filters_applied_sequentially(self) -> None:
        """Filters compose: injector adds text, then MaxTokens may trim."""
        f1 = SystemPromptInjector(extra_text="INJECTED")
        f2 = MaxTokensFilter(max_tokens=100_000)
        msgs = [_msg("user", "hello")]
        system = "base"

        for f in [f1, f2]:
            msgs, system = await f.filter(msgs, system)

        assert "INJECTED" in system
        assert len(msgs) == 1


# ---------------------------------------------------------------------------
# RuntimeConfig integration
# ---------------------------------------------------------------------------


class TestRuntimeConfigInputFilters:
    def test_input_filters_field_default_empty(self) -> None:
        cfg = RuntimeConfig(runtime_name="thin")
        assert cfg.input_filters == []

    def test_input_filters_field_accepts_filters(self) -> None:
        f = MaxTokensFilter(max_tokens=100)
        cfg = RuntimeConfig(runtime_name="thin", input_filters=[f])
        assert len(cfg.input_filters) == 1
        assert cfg.input_filters[0] is f
