"""Honest usage accounting for ThinRuntime finalization (Этап 26).

Audit finding: the live path never parses the provider's REAL ``usage`` (input/output/
cache token counts) — it always estimates via the repo-wide ~4 chars/token heuristic
(``_build_usage``), so ``compute_cost_cents`` bills against fabricated numbers and the
resulting ``RuntimeEvent.final.usage`` dict never says so.

This module pins the honest contract at the finalization layer (the single choke point
EVERY ThinRuntime strategy funnels through via ``finalize_with_validation``):

* When a caller has REAL provider usage for the exact call that produced the answer, it
  passes it via ``provider_usage=`` — the resulting ``usage`` dict carries those exact
  numbers and ``"estimated": False``.
* When no real usage is available (today: every live call site, until the provider
  adapters are updated to surface it — see ``llm_providers.py``), the existing ~4
  chars/token heuristic is used, but the result is now honestly marked
  ``"estimated": True`` instead of silently posing as ground truth.
* A structured-output RETRY produces a NEW answer from a NEW call — the ``provider_usage``
  supplied for the ORIGINAL attempt must never be reused for it (edge case: an
  already-parsed real usage for text A cannot honestly describe text B).

No network: a recording async ``llm_call`` stands in for the provider, exactly like the
existing ``test_structured_empty_retry.py``/``test_finalization_gate.py`` conventions.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.finalization import _build_usage, finalize_with_validation
from swarmline.runtime.thin.llm_client import (
    LlmCallResult,
    run_buffered_llm_call,
    try_stream_llm_call,
)
from swarmline.runtime.types import RuntimeConfig, RuntimeErrorData


class _Answer(BaseModel):
    answer: str = ""


def _config(**kwargs) -> RuntimeConfig:
    return RuntimeConfig(model="gpt-4o", **kwargs)


async def _drain(agen) -> list:
    return [event async for event in agen]


async def _unused_llm_call(messages, prompt, **kwargs):
    raise AssertionError("llm_call must not be invoked on the non-retry finalize path")


# ---------------------------------------------------------------------------
# _build_usage — pure helper contract
# ---------------------------------------------------------------------------


class TestBuildUsageHonestFlag:
    def test_missing_usage_falls_back_to_estimate_and_marks_estimated(self) -> None:
        """No real provider usage supplied -> heuristic numbers, honestly flagged."""
        usage = _build_usage(
            lm_messages=[{"role": "user", "content": "hello there"}],
            prompt="SYS",
            text="a reply",
        )

        assert usage["estimated"] is True
        assert usage["input_tokens"] > 0
        assert usage["output_tokens"] > 0
        assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]

    def test_usage_parsed_from_provider_response_populates_cost_event(self) -> None:
        """Real provider usage overrides the heuristic entirely and is marked non-estimated."""
        heuristic = _build_usage(
            lm_messages=[{"role": "user", "content": "hello there"}],
            prompt="SYS",
            text="a reply",
        )
        real_usage = {"input_tokens": 917, "output_tokens": 42, "total_tokens": 959}

        usage = _build_usage(
            lm_messages=[{"role": "user", "content": "hello there"}],
            prompt="SYS",
            text="a reply",
            provider_usage=real_usage,
        )

        assert usage["estimated"] is False
        assert usage["input_tokens"] == 917
        assert usage["output_tokens"] == 42
        assert usage["total_tokens"] == 959
        # Proves the REAL numbers were used, not the fabricated heuristic ones.
        assert usage["input_tokens"] != heuristic["input_tokens"]

    def test_provider_usage_cache_tokens_pass_through_when_present(self) -> None:
        """Cache read/write token counts (needed for cache hit-rate) survive untouched."""
        real_usage = {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "cache_read_tokens": 80,
            "cache_write_tokens": 5,
        }

        usage = _build_usage(
            lm_messages=[],
            prompt="SYS",
            text="x",
            provider_usage=real_usage,
        )

        assert usage["cache_read_tokens"] == 80
        assert usage["cache_write_tokens"] == 5

    def test_provider_usage_missing_total_tokens_is_derived(self) -> None:
        """A provider that omits total_tokens still gets an honest derived sum."""
        usage = _build_usage(
            lm_messages=[],
            prompt="SYS",
            text="x",
            provider_usage={"input_tokens": 10, "output_tokens": 5},
        )

        assert usage["total_tokens"] == 15
        assert usage["estimated"] is False


# ---------------------------------------------------------------------------
# finalize_with_validation — the real choke point every strategy calls through
# ---------------------------------------------------------------------------


class TestFinalizeWithValidationHonorsProviderUsage:
    @pytest.mark.asyncio
    async def test_finalize_without_provider_usage_marks_final_event_estimated(
        self,
    ) -> None:
        events = await _drain(
            finalize_with_validation(
                text="plain answer, no schema",
                config=_config(),
                lm_messages=[{"role": "user", "content": "go"}],
                prompt="SYS",
                llm_call=_unused_llm_call,
                start_time=time.monotonic(),
            )
        )

        final = events[-1]
        assert final.is_final
        assert final.data["usage"]["estimated"] is True

    @pytest.mark.asyncio
    async def test_finalize_with_provider_usage_populates_real_numbers_not_estimated(
        self,
    ) -> None:
        events = await _drain(
            finalize_with_validation(
                text="plain answer, no schema",
                config=_config(),
                lm_messages=[{"role": "user", "content": "go"}],
                prompt="SYS",
                llm_call=_unused_llm_call,
                start_time=time.monotonic(),
                provider_usage={
                    "input_tokens": 321,
                    "output_tokens": 12,
                    "total_tokens": 333,
                },
            )
        )

        final = events[-1]
        assert final.is_final
        usage = final.data["usage"]
        assert usage["estimated"] is False
        assert usage["input_tokens"] == 321
        assert usage["output_tokens"] == 12
        assert usage["total_tokens"] == 333

    @pytest.mark.asyncio
    async def test_structured_retry_success_never_reuses_original_provider_usage(
        self,
    ) -> None:
        """Edge case: a retried answer comes from a DIFFERENT LLM call — the caller's
        provider_usage (measured for the FIRST, invalid attempt) must not be attributed
        to the retried text. The retry-success path has no real usage of its own, so it
        must fall back to the honest estimate, not silently keep the stale real numbers."""

        async def llm_call(messages, prompt, **kwargs):
            return '{"answer": "done"}'

        events = await _drain(
            finalize_with_validation(
                text="not json",  # forces the retry loop
                config=_config(
                    output_type=_Answer,
                    output_format=_Answer.model_json_schema(),
                    max_model_retries=2,
                ),
                lm_messages=[{"role": "user", "content": "go"}],
                prompt="SYS",
                llm_call=llm_call,
                start_time=time.monotonic(),
                provider_usage={
                    "input_tokens": 999,
                    "output_tokens": 999,
                    "total_tokens": 1998,
                },
            )
        )

        final = events[-1]
        assert final.is_final
        usage = final.data["usage"]
        assert usage["estimated"] is True
        assert usage["input_tokens"] != 999


# ---------------------------------------------------------------------------
# llm_client.py plumbing — LlmCallResult.usage survives into the attempt objects
# every ThinRuntime strategy reads before calling finalize_with_validation.
# ---------------------------------------------------------------------------


class TestLlmClientPropagatesRealUsage:
    """Groundwork for provider adapters (llm_providers.py) to report real usage:
    once an adapter returns ``LlmCallResult(text=..., usage={...})``, the buffered AND
    streaming call helpers must carry it through untouched, ready for the strategy
    layer to hand to ``finalize_with_validation(provider_usage=...)``."""

    @pytest.mark.asyncio
    async def test_run_buffered_llm_call_carries_llm_call_result_usage(self) -> None:
        real_usage = {"input_tokens": 55, "output_tokens": 11, "total_tokens": 66}

        async def llm_call(messages, prompt, **kwargs):
            return LlmCallResult(text="hi", usage=real_usage)

        attempt = await run_buffered_llm_call(
            llm_call, [{"role": "user", "content": "go"}], "SYS"
        )

        assert attempt.raw == "hi"
        assert attempt.usage == real_usage

    @pytest.mark.asyncio
    async def test_run_buffered_llm_call_usage_defaults_to_none_for_plain_text(
        self,
    ) -> None:
        """Edge case: a provider that only ever returns a bare str (the common case
        today, since no adapter populates usage yet) leaves ``usage`` as None — the
        finalization layer then falls back to the honest estimate, never a stale value."""

        async def llm_call(messages, prompt, **kwargs):
            return "hi"

        attempt = await run_buffered_llm_call(
            llm_call, [{"role": "user", "content": "go"}], "SYS"
        )

        assert attempt.usage is None

    @pytest.mark.asyncio
    async def test_streaming_path_usage_arrives_attached_to_final_attempt(self) -> None:
        """Edge case: streaming — usage is only known once the FINAL chunk lands, so it
        is carried on the terminal ``StreamingLlmAttempt``, never on a per-delta event."""
        real_usage = {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}

        async def llm_call(messages, prompt, **kwargs):
            return LlmCallResult(text="streamed answer", usage=real_usage)

        attempt = await try_stream_llm_call(
            llm_call, [{"role": "user", "content": "go"}], "SYS"
        )

        assert attempt is not None
        assert attempt.raw == "streamed answer"
        assert attempt.usage == real_usage


# ---------------------------------------------------------------------------
# attempts — reconciliation signal (Fable-gate rider, Этап 26): a provider MAY bill
# tokens for a partially-generated FAILED attempt that never reaches swarmline's usage
# accounting (e.g. a mid-stream timeout). attempts>1 flags that the cost event's
# input/output tokens could undercount what the provider actually billed for the whole
# logical call, not just the winning attempt.
# ---------------------------------------------------------------------------


class _CountingRetryPolicy:
    """Always retries (zero delay) up to `max_retries` transient failures."""

    def __init__(self, max_retries: int) -> None:
        self.max_retries = max_retries

    def should_retry(self, error: Exception, attempt: int) -> tuple[bool, float]:
        return attempt < self.max_retries, 0.0


def _retryable_error() -> ThinLlmError:
    return ThinLlmError(
        RuntimeErrorData(kind="provider_unavailable", message="503", recoverable=True)
    )


class TestRunBufferedLlmCallTracksAttempts:
    @pytest.mark.asyncio
    async def test_no_retry_reports_attempts_one(self) -> None:
        async def llm_call(messages, prompt, **kwargs):
            return "hi"

        attempt = await run_buffered_llm_call(
            llm_call, [{"role": "user", "content": "go"}], "SYS"
        )

        assert attempt.attempts == 1

    @pytest.mark.asyncio
    async def test_two_transient_failures_then_success_reports_attempts_three(
        self,
    ) -> None:
        calls = {"n": 0}

        async def llm_call(messages, prompt, **kwargs):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise _retryable_error()
            return "recovered"

        attempt = await run_buffered_llm_call(
            llm_call,
            [{"role": "user", "content": "go"}],
            "SYS",
            retry_policy=_CountingRetryPolicy(max_retries=5),
        )

        assert attempt.raw == "recovered"
        assert attempt.attempts == 3, "2 failed HTTP attempts + 1 winning attempt"

    @pytest.mark.asyncio
    async def test_retry_then_success_carries_llm_call_result_usage_and_attempts(
        self,
    ) -> None:
        """The winning attempt's real usage AND the total attempt count both reach the
        caller — a downstream reconciliation job can cross-check billed tokens against
        attempts>1 without re-deriving retry history from logs."""
        calls = {"n": 0}
        real_usage = {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16}

        async def llm_call(messages, prompt, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _retryable_error()
            return LlmCallResult(text="ok", usage=real_usage)

        attempt = await run_buffered_llm_call(
            llm_call,
            [{"role": "user", "content": "go"}],
            "SYS",
            retry_policy=_CountingRetryPolicy(max_retries=5),
        )

        assert attempt.usage == real_usage
        assert attempt.attempts == 2


class TestFinalizeWithValidationCarriesAttempts:
    @pytest.mark.asyncio
    async def test_attempts_default_one_when_not_supplied(self) -> None:
        events = await _drain(
            finalize_with_validation(
                text="plain answer",
                config=_config(),
                lm_messages=[{"role": "user", "content": "go"}],
                prompt="SYS",
                llm_call=_unused_llm_call,
                start_time=time.monotonic(),
            )
        )

        final = events[-1]
        assert final.data["usage"]["attempts"] == 1

    @pytest.mark.asyncio
    async def test_attempts_from_caller_reaches_final_usage(self) -> None:
        events = await _drain(
            finalize_with_validation(
                text="plain answer",
                config=_config(),
                lm_messages=[{"role": "user", "content": "go"}],
                prompt="SYS",
                llm_call=_unused_llm_call,
                start_time=time.monotonic(),
                provider_usage={"input_tokens": 1, "output_tokens": 1},
                attempts=3,
            )
        )

        final = events[-1]
        assert final.data["usage"]["attempts"] == 3

    @pytest.mark.asyncio
    async def test_structured_retry_success_reports_its_own_attempts_not_originals(
        self,
    ) -> None:
        """Same one-call-only scoping as provider_usage: the structured-retry-success
        path is a DIFFERENT LLM call — it must report ITS OWN attempts (default 1), not
        the original (pre-retry) attempt count the caller supplied."""

        async def llm_call(messages, prompt, **kwargs):
            return '{"answer": "done"}'

        events = await _drain(
            finalize_with_validation(
                text="not json",
                config=_config(
                    output_type=_Answer,
                    output_format=_Answer.model_json_schema(),
                    max_model_retries=2,
                ),
                lm_messages=[{"role": "user", "content": "go"}],
                prompt="SYS",
                llm_call=llm_call,
                start_time=time.monotonic(),
                attempts=9,
            )
        )

        final = events[-1]
        assert final.data["usage"]["attempts"] == 1


class TestConversationalStrategyCarriesAttempts:
    @pytest.mark.asyncio
    async def test_buffered_path_retry_count_reaches_final_usage(self) -> None:
        from swarmline.runtime.thin.conversational import run_conversational

        calls = {"n": 0}

        async def llm_call(messages, prompt, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _retryable_error()
            return LlmCallResult(text='{"type": "final", "final_message": "hi"}')

        config = _config(retry_policy=_CountingRetryPolicy(max_retries=5))

        events = await _drain(
            run_conversational(
                llm_call,
                messages=[],
                system_prompt="sys",
                config=config,
                start_time=time.monotonic(),
            )
        )

        final = next(e for e in events if e.is_final)
        assert final.data["usage"]["attempts"] == 2


# ---------------------------------------------------------------------------
# llm_providers.py — the ONE currently-safe real-usage extraction site.
#
# NOTE (scope, see final report): only the Anthropic extended-thinking branch is wired
# here. It already returns ``LlmCallResult`` (pinned by existing behaviour — see
# test_llm_providers.py), so adding ``usage`` is purely additive. The plain-text
# branches of ALL THREE adapters still return a bare ``str`` — several direct
# ``llm_call(...)`` call sites in conversational.py/react_strategy.py/planner_strategy.py
# assume that contract unconditionally (e.g. test_llm_providers.py::
# test_call_invokes_messages_create pins ``result == "Hello from Claude"``) and are NOT
# touched this stage — a broader, higher-risk refactor is required to make the general
# (non-thinking) case honest too. Tracked as a follow-up, not fixed here.
# ---------------------------------------------------------------------------


def _make_mock_anthropic_module() -> MagicMock:
    mock_module = MagicMock()
    mock_module.AsyncAnthropic.return_value = AsyncMock()
    mock_module.AuthenticationError = type("AuthenticationError", (Exception,), {})
    mock_module.APIConnectionError = type("APIConnectionError", (Exception,), {})
    mock_module.APIStatusError = type("APIStatusError", (Exception,), {})
    return mock_module


class TestAnthropicThinkingBranchExtractsRealUsage:
    @pytest.mark.asyncio
    async def test_anthropic_thinking_response_usage_populates_llm_call_result(
        self,
    ) -> None:
        from swarmline.domain_types import ThinkingConfig
        from swarmline.runtime.thin.llm_providers import AnthropicAdapter

        mock_module = _make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")

            thinking_block = MagicMock()
            thinking_block.type = "thinking"
            thinking_block.thinking = "let me think"
            text_block = MagicMock()
            text_block.type = "text"
            text_block.text = "the answer"
            del text_block.thinking  # hasattr(block, "thinking") must be False

            mock_usage = MagicMock()
            mock_usage.input_tokens = 200
            mock_usage.output_tokens = 30
            mock_usage.cache_read_input_tokens = 150
            mock_usage.cache_creation_input_tokens = 0

            mock_response = MagicMock()
            mock_response.content = [thinking_block, text_block]
            mock_response.usage = mock_usage
            adapter._client.messages.create = AsyncMock(return_value=mock_response)

            result = await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="sys",
                _thinking_config=ThinkingConfig(budget_tokens=5000),
            )

        assert result.text == "the answer"
        assert result.thinking == "let me think"
        assert result.usage == {
            "input_tokens": 200,
            "output_tokens": 30,
            "total_tokens": 230,
            "cache_read_tokens": 150,
            "cache_write_tokens": 0,
        }

    @pytest.mark.asyncio
    async def test_anthropic_thinking_response_without_usage_field_is_none(
        self,
    ) -> None:
        """A test double (or a future SDK shape change) with no usable ``usage`` block
        must not fabricate numbers — the caller falls back to the honest estimate."""
        from swarmline.domain_types import ThinkingConfig
        from swarmline.runtime.thin.llm_providers import AnthropicAdapter

        mock_module = _make_mock_anthropic_module()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")

            thinking_block = MagicMock()
            thinking_block.type = "thinking"
            thinking_block.thinking = "hmm"

            mock_response = MagicMock(spec=["content"])
            mock_response.content = [thinking_block]
            adapter._client.messages.create = AsyncMock(return_value=mock_response)

            result = await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="sys",
                _thinking_config=ThinkingConfig(budget_tokens=5000),
            )

        assert result.usage is None


# ---------------------------------------------------------------------------
# run_conversational — end-to-end reachability proof for the buffered AND
# streaming branches (the only strategy wired to ``provider_usage=`` this stage).
# ---------------------------------------------------------------------------


class TestConversationalStrategyHonorsRealUsage:
    @pytest.mark.asyncio
    async def test_buffered_path_final_event_uses_real_llm_call_result_usage(
        self,
    ) -> None:
        from swarmline.runtime.thin.conversational import run_conversational

        real_usage = {"input_tokens": 42, "output_tokens": 7, "total_tokens": 49}

        async def llm_call(messages, prompt, **kwargs):
            return LlmCallResult(
                text='{"type": "final", "final_message": "hi there"}',
                usage=real_usage,
            )

        config = _config(retry_policy=object())  # forces buffered_postprocessing=True

        events = await _drain(
            run_conversational(
                llm_call,
                messages=[],
                system_prompt="sys",
                config=config,
                start_time=time.monotonic(),
            )
        )

        final = next(e for e in events if e.is_final)
        assert final.text == "hi there"
        assert final.data["usage"] == {
            **real_usage,
            "estimated": False,
            "attempts": 1,
            "usage_source": "native",
        }

    @pytest.mark.asyncio
    async def test_streaming_path_final_event_uses_real_usage_from_final_chunk(
        self,
    ) -> None:
        """Edge case: streaming — the ONLY usage available arrives attached to the
        terminal chunk (``LlmCallResult.usage`` on the non-async-iterator branch of
        ``stream_llm_call``); it must still reach the final ``RuntimeEvent``."""
        from swarmline.runtime.thin.conversational import run_conversational

        real_usage = {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}

        async def llm_call(messages, prompt, **kwargs):
            assert kwargs.get("stream") is True
            return LlmCallResult(
                text='{"type": "final", "final_message": "streamed hi"}',
                usage=real_usage,
            )

        events = await _drain(
            run_conversational(
                llm_call,
                messages=[],
                system_prompt="sys",
                config=_config(),
                start_time=time.monotonic(),
            )
        )

        final = next(e for e in events if e.is_final)
        assert final.text == "streamed hi"
        assert final.data["usage"] == {
            **real_usage,
            "estimated": False,
            "attempts": 1,
            "usage_source": "native",
        }
