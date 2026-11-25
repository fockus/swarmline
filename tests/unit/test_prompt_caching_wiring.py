"""Unit tests: prompt caching (Stage 2, context-engineering-manus-parity) — infra wiring.

Covers:
  - AnthropicAdapter.call()/.stream(): cache_control breakpoints applied ONLY when
    ``_prompt_caching_enabled=True`` is passed; opt-out (absent/False) is a byte-identical
    payload contract vs. the pre-Stage-2 request shape.
  - Usage log: cache_read_input_tokens/cache_creation_input_tokens logged from the
    provider's real usage block.
  - default_llm_call(): threads ``RuntimeConfig.native_config["prompt_caching_enabled"]``
    into the adapter call ONLY for the native Anthropic path (sdk_type == "anthropic");
    no-op (kwarg never forwarded) for every other provider.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarmline.runtime.provider_resolver import ResolvedProvider
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.llm_client import default_llm_call, run_buffered_llm_call
from swarmline.runtime.thin.llm_providers import AnthropicAdapter
from swarmline.runtime.types import RuntimeConfig, RuntimeErrorData


def _make_mock_anthropic_module() -> MagicMock:
    mock_module = MagicMock()
    mock_module.AsyncAnthropic.return_value = AsyncMock()
    mock_module.AuthenticationError = type("AuthenticationError", (Exception,), {})
    mock_module.APIConnectionError = type("APIConnectionError", (Exception,), {})
    mock_module.APIStatusError = type("APIStatusError", (Exception,), {})
    return mock_module


@pytest.fixture(autouse=True)
def _clear_adapter_cache() -> None:
    from swarmline.runtime.thin.llm_providers import _adapter_cache

    _adapter_cache.clear()
    yield
    _adapter_cache.clear()


def _mock_anthropic_client(
    usage: MagicMock | None = None,
) -> tuple[MagicMock, AsyncMock]:
    mock_module = _make_mock_anthropic_module()
    mock_client = AsyncMock()
    text_block = MagicMock(spec=["type", "text"])
    text_block.type = "text"
    text_block.text = "ok"
    mock_response = MagicMock()
    mock_response.content = [text_block]
    mock_response.usage = usage
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    mock_module.AsyncAnthropic.return_value = mock_client
    return mock_module, mock_client


# ---------------------------------------------------------------------------
# AnthropicAdapter.call() — cache_control breakpoint placement
# ---------------------------------------------------------------------------


class TestAnthropicAdapterCacheControlOptOut:
    @pytest.mark.asyncio
    async def test_flag_absent_payload_byte_identical_to_pre_stage2_shape(self) -> None:
        mock_module, mock_client = _mock_anthropic_client()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="You are helpful.",
            )
            kwargs = mock_client.messages.create.call_args.kwargs
            assert kwargs["system"] == "You are helpful."
            assert kwargs["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_flag_absent_full_kwargs_dict_is_golden_equal(self) -> None:
        """Fix-cycle 1 (MINOR-3): checking individual keys isn't enough — golden
        equality of the WHOLE serialized kwargs dict proves no stray key was added
        and nothing else in the payload shape changed."""
        mock_module, mock_client = _mock_anthropic_client()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="You are helpful.",
            )
            kwargs = mock_client.messages.create.call_args.kwargs

        assert kwargs == {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4096,
            "system": "You are helpful.",
            "messages": [{"role": "user", "content": "hi"}],
        }

    @pytest.mark.asyncio
    async def test_flag_explicitly_false_same_as_absent(self) -> None:
        mock_module, mock_client = _mock_anthropic_client()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="You are helpful.",
                _prompt_caching_enabled=False,
            )
            kwargs = mock_client.messages.create.call_args.kwargs
            assert kwargs["system"] == "You are helpful."
            assert kwargs["messages"] == [{"role": "user", "content": "hi"}]


class TestAnthropicAdapterCacheControlEnabled:
    @pytest.mark.asyncio
    async def test_system_and_last_messages_get_cache_control(self) -> None:
        mock_module, mock_client = _mock_anthropic_client()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=[
                    {"role": "user", "content": "one"},
                    {"role": "assistant", "content": "two"},
                    {"role": "user", "content": "three"},
                    {"role": "assistant", "content": "four"},
                ],
                system_prompt="You are helpful.",
                _prompt_caching_enabled=True,
            )
            kwargs = mock_client.messages.create.call_args.kwargs

            assert kwargs["system"] == [
                {
                    "type": "text",
                    "text": "You are helpful.",
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            sent_messages = kwargs["messages"]
            assert (
                sent_messages[0]["content"] == "one"
            )  # not one of the last 3 -> untouched
            for msg in sent_messages[1:]:
                assert msg["content"][-1]["cache_control"] == {"type": "ephemeral"}

    @pytest.mark.asyncio
    async def test_at_most_four_total_breakpoints(self) -> None:
        mock_module, mock_client = _mock_anthropic_client()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=[{"role": "user", "content": f"m{i}"} for i in range(6)],
                system_prompt="Sys.",
                _prompt_caching_enabled=True,
            )
            kwargs = mock_client.messages.create.call_args.kwargs

            total_breakpoints = 1  # system always counts as 1 when non-blank
            for msg in kwargs["messages"]:
                content = msg["content"]
                if isinstance(content, list) and any(
                    "cache_control" in b for b in content
                ):
                    total_breakpoints += 1
            assert total_breakpoints == 4

    @pytest.mark.asyncio
    async def test_empty_content_message_never_gets_a_breakpoint(self) -> None:
        mock_module, mock_client = _mock_anthropic_client()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=[
                    {"role": "user", "content": "keep"},
                    {"role": "assistant", "content": ""},
                ],
                system_prompt="Sys.",
                _prompt_caching_enabled=True,
            )
            kwargs = mock_client.messages.create.call_args.kwargs
            assert kwargs["messages"][1]["content"] == ""

    @pytest.mark.asyncio
    async def test_boundary_marker_in_system_prompt_splits_static_and_dynamic(
        self,
    ) -> None:
        """Fix-cycle 1 BLOCKER, adapter-level (splitter side already covered at the
        pure-function level in test_context_prompt_caching.py; this closes the loop
        end-to-end through AnthropicAdapter.call())."""
        mock_module, mock_client = _mock_anthropic_client()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="Static rules.<!-- TASKLOOM_CACHE_BOUNDARY -->Dynamic plan.",
                _prompt_caching_enabled=True,
            )
            kwargs = mock_client.messages.create.call_args.kwargs

        assert kwargs["system"] == [
            {
                "type": "text",
                "text": "Static rules.",
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": "Dynamic plan."},
        ]

    @pytest.mark.asyncio
    async def test_default_ttl_is_5m(self) -> None:
        mock_module, mock_client = _mock_anthropic_client()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="Sys.",
                _prompt_caching_enabled=True,
            )
            kwargs = mock_client.messages.create.call_args.kwargs

        assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}

    @pytest.mark.asyncio
    async def test_explicit_1h_ttl_forwarded_to_both_system_and_messages(self) -> None:
        mock_module, mock_client = _mock_anthropic_client()
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="Sys.",
                _prompt_caching_enabled=True,
                _prompt_caching_ttl="1h",
            )
            kwargs = mock_client.messages.create.call_args.kwargs

        assert kwargs["system"][0]["cache_control"] == {
            "type": "ephemeral",
            "ttl": "1h",
        }
        assert kwargs["messages"][0]["content"][-1]["cache_control"] == {
            "type": "ephemeral",
            "ttl": "1h",
        }

    @pytest.mark.asyncio
    async def test_decoration_failure_falls_back_to_uncached_request_fail_open(
        self,
    ) -> None:
        """Fix-cycle 1 (MAJOR-5, guarded decoration): an unexpected error raised while
        building the cache_control decoration must never break the underlying LLM
        call — falls back to the plain (uncached) request."""
        mock_module, mock_client = _mock_anthropic_client()
        with (
            patch.dict("sys.modules", {"anthropic": mock_module}),
            patch(
                "swarmline.runtime.thin.llm_providers.build_cached_system",
                side_effect=RuntimeError("boom"),
            ),
        ):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            result = await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="Sys.",
                _prompt_caching_enabled=True,
            )

        assert result == "ok"
        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["system"] == "Sys."
        assert kwargs["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_idempotent_across_retried_attempts(self) -> None:
        """Same call() invoked twice with the SAME original messages (simulating a
        retry) must produce byte-identical cache_control placement both times."""
        mock_module, mock_client = _mock_anthropic_client()
        original_messages = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
        ]
        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=original_messages,
                system_prompt="Sys.",
                _prompt_caching_enabled=True,
            )
            first_kwargs = dict(mock_client.messages.create.call_args.kwargs)
            await adapter.call(
                messages=original_messages,
                system_prompt="Sys.",
                _prompt_caching_enabled=True,
            )
            second_kwargs = dict(mock_client.messages.create.call_args.kwargs)

            assert first_kwargs["system"] == second_kwargs["system"]
            assert first_kwargs["messages"] == second_kwargs["messages"]
            assert original_messages == [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "two"},
            ]

    @pytest.mark.asyncio
    async def test_idempotent_through_the_real_retry_loop(self) -> None:
        """Fix-cycle 1 (MINOR-3): idempotency proven through the ACTUAL retry code
        path (``run_buffered_llm_call``), not by manually invoking ``adapter.call()``
        twice — a transient failure on attempt 1 must retry and reproduce the SAME
        cache_control placement on attempt 2."""
        mock_module, mock_client = _mock_anthropic_client()
        original_create = mock_client.messages.create
        call_count = {"n": 0}

        async def _flaky_create(**kwargs: object) -> object:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ThinLlmError(
                    RuntimeErrorData(kind="transient", message="boom", recoverable=True)
                )
            return await original_create(**kwargs)

        mock_client.messages.create = AsyncMock(side_effect=_flaky_create)

        original_messages = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
        ]

        class _RetryOnce:
            def should_retry(self, exc: Exception, attempt: int) -> tuple[bool, float]:  # noqa: ARG002
                return (attempt == 0, 0.0)

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client

            attempt = await run_buffered_llm_call(
                adapter.call,
                original_messages,
                "Sys.",
                retry_policy=_RetryOnce(),
                llm_kwargs={"_prompt_caching_enabled": True},
            )

        assert attempt.attempts == 2
        assert call_count["n"] == 2
        first_kwargs = mock_client.messages.create.call_args_list[0].kwargs
        second_kwargs = mock_client.messages.create.call_args_list[1].kwargs
        assert first_kwargs["system"] == second_kwargs["system"]
        assert first_kwargs["messages"] == second_kwargs["messages"]
        assert second_kwargs["messages"][-1]["content"][-1]["cache_control"] == {
            "type": "ephemeral"
        }


class TestAnthropicAdapterStreamCacheControl:
    @pytest.mark.asyncio
    async def test_stream_applies_cache_control_when_enabled(self) -> None:
        mock_module = _make_mock_anthropic_module()
        mock_client = AsyncMock()

        class _FakeStreamCtx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            @property
            async def text_stream(self):
                for chunk in ("ok",):
                    yield chunk

            async def get_final_message(self):
                return MagicMock(usage=None)

        mock_client.messages.stream = MagicMock(return_value=_FakeStreamCtx())
        mock_module.AsyncAnthropic.return_value = mock_client

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            chunks = [
                c
                async for c in adapter.stream(
                    messages=[{"role": "user", "content": "hi"}],
                    system_prompt="Sys.",
                    _prompt_caching_enabled=True,
                )
            ]

            assert chunks == ["ok"]
            call_kwargs = mock_client.messages.stream.call_args.kwargs
            assert call_kwargs["system"] == [
                {"type": "text", "text": "Sys.", "cache_control": {"type": "ephemeral"}}
            ]
            assert call_kwargs["messages"][0]["content"][-1]["cache_control"] == {
                "type": "ephemeral"
            }


# ---------------------------------------------------------------------------
# Cache usage log — cache_read_input_tokens / cache_creation_input_tokens
# ---------------------------------------------------------------------------


class TestAnthropicAdapterCacheUsageLog:
    @pytest.mark.asyncio
    async def test_logs_cache_read_and_creation_tokens_when_present(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        usage = MagicMock(
            input_tokens=100,
            output_tokens=20,
            cache_read_input_tokens=80,
            cache_creation_input_tokens=15,
        )
        mock_module, mock_client = _mock_anthropic_client(usage=usage)
        with (
            patch.dict("sys.modules", {"anthropic": mock_module}),
            caplog.at_level(logging.INFO),
        ):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="Sys.",
                _prompt_caching_enabled=True,
            )

        cache_records = [
            r for r in caplog.records if "cache_read_input_tokens" in r.getMessage()
        ]
        assert cache_records, (
            "expected a usage log line mentioning cache_read_input_tokens"
        )
        assert "80" in cache_records[0].getMessage()
        assert "15" in cache_records[0].getMessage()

    @pytest.mark.asyncio
    async def test_missing_cache_fields_still_log_normalized_zero_not_skipped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Fix-cycle 1 (MAJOR-3): 'every completed call' means the log line is ALWAYS
        present — missing cache fields normalize to 0, never silently skip the log."""
        usage = MagicMock(
            spec=["input_tokens", "output_tokens"], input_tokens=10, output_tokens=5
        )
        mock_module, mock_client = _mock_anthropic_client(usage=usage)
        with (
            patch.dict("sys.modules", {"anthropic": mock_module}),
            caplog.at_level(logging.INFO),
        ):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            result = await adapter.call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="Sys.",
            )
            assert result == "ok"

        cache_records = [
            r for r in caplog.records if "cache_read_input_tokens" in r.getMessage()
        ]
        assert cache_records, "usage log line must be present even without cache fields"
        assert "cache_read_input_tokens=0" in cache_records[0].getMessage()
        assert "cache_creation_input_tokens=0" in cache_records[0].getMessage()

    @pytest.mark.asyncio
    async def test_stream_logs_usage_every_completed_call(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        usage = MagicMock(cache_read_input_tokens=7, cache_creation_input_tokens=3)
        mock_module = _make_mock_anthropic_module()
        mock_client = AsyncMock()

        class _FakeStreamCtx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            @property
            async def text_stream(self):
                for chunk in ("ok",):
                    yield chunk

            async def get_final_message(self):
                return MagicMock(usage=usage)

        mock_client.messages.stream = MagicMock(return_value=_FakeStreamCtx())
        mock_module.AsyncAnthropic.return_value = mock_client

        with (
            patch.dict("sys.modules", {"anthropic": mock_module}),
            caplog.at_level(logging.INFO),
        ):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            _ = [
                c
                async for c in adapter.stream(
                    messages=[{"role": "user", "content": "hi"}], system_prompt="Sys."
                )
            ]

        cache_records = [
            r for r in caplog.records if "cache_read_input_tokens" in r.getMessage()
        ]
        assert cache_records
        assert "cache_read_input_tokens=7" in cache_records[0].getMessage()
        assert "cache_creation_input_tokens=3" in cache_records[0].getMessage()

    @pytest.mark.asyncio
    async def test_call_with_tools_logs_usage_every_completed_call(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Fix-cycle 1 (MAJOR-3): the usage log was entirely missing from the native
        tool-calling path — it must fire there too, on every completed call."""
        usage = MagicMock(cache_read_input_tokens=42, cache_creation_input_tokens=9)
        mock_module = _make_mock_anthropic_module()
        mock_client = AsyncMock()
        text_block = MagicMock(spec=["type", "text"])
        text_block.type = "text"
        text_block.text = "ok"
        mock_response = MagicMock()
        mock_response.content = [text_block]
        mock_response.usage = usage
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_module.AsyncAnthropic.return_value = mock_client

        with (
            patch.dict("sys.modules", {"anthropic": mock_module}),
            caplog.at_level(logging.INFO),
        ):
            adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
            adapter._client = mock_client
            await adapter.call_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="Sys.",
                tools=[],
            )

        cache_records = [
            r for r in caplog.records if "cache_read_input_tokens" in r.getMessage()
        ]
        assert cache_records, (
            "call_with_tools must log usage too (was missing entirely)"
        )
        assert "cache_read_input_tokens=42" in cache_records[0].getMessage()
        assert "cache_creation_input_tokens=9" in cache_records[0].getMessage()


# ---------------------------------------------------------------------------
# default_llm_call — RuntimeConfig.native_config threading (Anthropic-only, no-op elsewhere)
# ---------------------------------------------------------------------------


class TestDefaultLlmCallPromptCachingThreading:
    @pytest.mark.asyncio
    async def test_anthropic_with_flag_true_forwards_kwarg(self) -> None:
        config = RuntimeConfig(
            runtime_name="thin",
            model="claude-sonnet-4-20250514",
            native_config={"prompt_caching_enabled": True},
        )
        with (
            patch(
                "swarmline.runtime.thin.llm_client.get_cached_adapter"
            ) as mock_factory,
            patch("swarmline.runtime.thin.llm_client.resolve_provider") as mock_resolve,
        ):
            mock_resolve.return_value = ResolvedProvider(
                "claude-sonnet-4-20250514", "anthropic", "anthropic", None
            )
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="response")
            mock_factory.return_value = mock_adapter

            await default_llm_call(
                config, [{"role": "user", "content": "hi"}], "system"
            )

            call_kwargs = mock_adapter.call.call_args.kwargs
            assert call_kwargs.get("_prompt_caching_enabled") is True

    @pytest.mark.asyncio
    async def test_default_ttl_forwarded_is_5m(self) -> None:
        config = RuntimeConfig(
            runtime_name="thin",
            model="claude-sonnet-4-20250514",
            native_config={"prompt_caching_enabled": True},
        )
        with (
            patch(
                "swarmline.runtime.thin.llm_client.get_cached_adapter"
            ) as mock_factory,
            patch("swarmline.runtime.thin.llm_client.resolve_provider") as mock_resolve,
        ):
            mock_resolve.return_value = ResolvedProvider(
                "claude-sonnet-4-20250514", "anthropic", "anthropic", None
            )
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="response")
            mock_factory.return_value = mock_adapter

            await default_llm_call(
                config, [{"role": "user", "content": "hi"}], "system"
            )

            call_kwargs = mock_adapter.call.call_args.kwargs
            assert call_kwargs.get("_prompt_caching_ttl") == "5m"

    @pytest.mark.asyncio
    async def test_explicit_1h_ttl_forwarded(self) -> None:
        config = RuntimeConfig(
            runtime_name="thin",
            model="claude-sonnet-4-20250514",
            native_config={"prompt_caching_enabled": True, "prompt_caching_ttl": "1h"},
        )
        with (
            patch(
                "swarmline.runtime.thin.llm_client.get_cached_adapter"
            ) as mock_factory,
            patch("swarmline.runtime.thin.llm_client.resolve_provider") as mock_resolve,
        ):
            mock_resolve.return_value = ResolvedProvider(
                "claude-sonnet-4-20250514", "anthropic", "anthropic", None
            )
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="response")
            mock_factory.return_value = mock_adapter

            await default_llm_call(
                config, [{"role": "user", "content": "hi"}], "system"
            )

            call_kwargs = mock_adapter.call.call_args.kwargs
            assert call_kwargs.get("_prompt_caching_ttl") == "1h"

    @pytest.mark.asyncio
    async def test_ttl_not_forwarded_when_caching_disabled(self) -> None:
        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")
        with (
            patch(
                "swarmline.runtime.thin.llm_client.get_cached_adapter"
            ) as mock_factory,
            patch("swarmline.runtime.thin.llm_client.resolve_provider") as mock_resolve,
        ):
            mock_resolve.return_value = ResolvedProvider(
                "claude-sonnet-4-20250514", "anthropic", "anthropic", None
            )
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="response")
            mock_factory.return_value = mock_adapter

            await default_llm_call(
                config, [{"role": "user", "content": "hi"}], "system"
            )

            call_kwargs = mock_adapter.call.call_args.kwargs
            assert "_prompt_caching_ttl" not in call_kwargs

    @pytest.mark.asyncio
    async def test_anthropic_without_native_config_key_does_not_forward_kwarg(
        self,
    ) -> None:
        """Contract: opt-out (key absent, the RuntimeConfig() default) must not add the
        kwarg at all — byte-identical to the pre-Stage-2 kwargs dict."""
        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")
        with (
            patch(
                "swarmline.runtime.thin.llm_client.get_cached_adapter"
            ) as mock_factory,
            patch("swarmline.runtime.thin.llm_client.resolve_provider") as mock_resolve,
        ):
            mock_resolve.return_value = ResolvedProvider(
                "claude-sonnet-4-20250514", "anthropic", "anthropic", None
            )
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="response")
            mock_factory.return_value = mock_adapter

            await default_llm_call(
                config, [{"role": "user", "content": "hi"}], "system"
            )

            call_kwargs = mock_adapter.call.call_args.kwargs
            assert "_prompt_caching_enabled" not in call_kwargs

    @pytest.mark.asyncio
    async def test_anthropic_with_flag_explicitly_false_does_not_forward_kwarg(
        self,
    ) -> None:
        config = RuntimeConfig(
            runtime_name="thin",
            model="claude-sonnet-4-20250514",
            native_config={"prompt_caching_enabled": False},
        )
        with (
            patch(
                "swarmline.runtime.thin.llm_client.get_cached_adapter"
            ) as mock_factory,
            patch("swarmline.runtime.thin.llm_client.resolve_provider") as mock_resolve,
        ):
            mock_resolve.return_value = ResolvedProvider(
                "claude-sonnet-4-20250514", "anthropic", "anthropic", None
            )
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="response")
            mock_factory.return_value = mock_adapter

            await default_llm_call(
                config, [{"role": "user", "content": "hi"}], "system"
            )

            call_kwargs = mock_adapter.call.call_args.kwargs
            assert "_prompt_caching_enabled" not in call_kwargs

    @pytest.mark.asyncio
    async def test_non_anthropic_provider_with_flag_true_is_a_noop(self) -> None:
        """No-op contract: the flag is set in native_config but the resolved provider is
        NOT Anthropic (e.g. OpenAI/OpenRouter) -> kwarg must never be forwarded."""
        config = RuntimeConfig(
            runtime_name="thin",
            model="openai:gpt-4o",
            native_config={"prompt_caching_enabled": True},
        )
        with (
            patch(
                "swarmline.runtime.thin.llm_client.get_cached_adapter"
            ) as mock_factory,
            patch("swarmline.runtime.thin.llm_client.resolve_provider") as mock_resolve,
        ):
            mock_resolve.return_value = ResolvedProvider(
                "gpt-4o", "openai", "openai_compat", None
            )
            mock_adapter = AsyncMock()
            mock_adapter.call = AsyncMock(return_value="response")
            mock_factory.return_value = mock_adapter

            await default_llm_call(
                config, [{"role": "user", "content": "hi"}], "system"
            )

            call_kwargs = mock_adapter.call.call_args.kwargs
            assert "_prompt_caching_enabled" not in call_kwargs

    @pytest.mark.asyncio
    async def test_streaming_path_also_receives_the_flag(self) -> None:
        """The stream branch shares the same kwargs dict as the buffered call branch."""
        config = RuntimeConfig(
            runtime_name="thin",
            model="claude-sonnet-4-20250514",
            native_config={"prompt_caching_enabled": True},
        )
        with (
            patch(
                "swarmline.runtime.thin.llm_client.get_cached_adapter"
            ) as mock_factory,
            patch("swarmline.runtime.thin.llm_client.resolve_provider") as mock_resolve,
        ):
            mock_resolve.return_value = ResolvedProvider(
                "claude-sonnet-4-20250514", "anthropic", "anthropic", None
            )

            async def _fake_stream(*_args, **_kwargs):
                yield "chunk"

            mock_adapter = MagicMock()
            mock_adapter.stream = MagicMock(side_effect=_fake_stream)
            mock_factory.return_value = mock_adapter

            result = await default_llm_call(
                config, [{"role": "user", "content": "hi"}], "system", stream=True
            )
            _ = [c async for c in result]

            stream_kwargs = mock_adapter.stream.call_args.kwargs
            assert stream_kwargs.get("_prompt_caching_enabled") is True
