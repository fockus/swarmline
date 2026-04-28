"""Integration tests for guardrails with ThinRuntime.

Tests cover:
- Input guardrail blocks input -> error event
- Output guardrail blocks output -> error event
- Multiple guardrails run in parallel
- No guardrails -> backward compat (normal flow)
"""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.guardrails import (
    ContentLengthGuardrail,
    RegexGuardrail,
)
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_call(response: str):
    """Create a fake llm_call that returns a fixed response."""

    async def llm_call(
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str:
        return response

    return llm_call


def _make_streaming_llm_call(chunks: list[str], fallback_response: str | None = None):
    """Create a fake llm_call that streams chunks when stream=True."""

    async def llm_call(
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> Any:
        if kwargs.get("stream"):

            async def _stream():
                for chunk in chunks:
                    yield chunk

            return _stream()
        return fallback_response if fallback_response is not None else "".join(chunks)

    return llm_call


VALID_FINAL_JSON = '{"type": "final", "final_message": "Hello, world!"}'
SECRET_FINAL_JSON = '{"type": "final", "final_message": "The SECRET_123 is leaked"}'


async def _collect_events(
    runtime: ThinRuntime, user_text: str = "hi"
) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for ev in runtime.run(
        messages=[Message(role="user", content=user_text)],
        system_prompt="You are a helper.",
        active_tools=[],
    ):
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Input guardrail blocks input
# ---------------------------------------------------------------------------


class TestInputGuardrailBlocks:
    @pytest.mark.asyncio
    async def test_input_guardrail_blocks_long_input(self) -> None:
        cfg = RuntimeConfig(
            runtime_name="thin",
            input_guardrails=[ContentLengthGuardrail(max_length=10)],
        )
        runtime = ThinRuntime(
            config=cfg,
            llm_call=_make_llm_call(VALID_FINAL_JSON),
        )

        events = await _collect_events(runtime, user_text="x" * 20)

        error_events = [e for e in events if e.is_error]
        assert len(error_events) >= 1
        err = error_events[0]
        assert err.data["kind"] == "guardrail_tripwire"

    @pytest.mark.asyncio
    async def test_input_guardrail_regex_blocks_forbidden_pattern(self) -> None:
        cfg = RuntimeConfig(
            runtime_name="thin",
            input_guardrails=[RegexGuardrail(patterns=[r"DROP TABLE"])],
        )
        runtime = ThinRuntime(
            config=cfg,
            llm_call=_make_llm_call(VALID_FINAL_JSON),
        )

        events = await _collect_events(runtime, user_text="Please DROP TABLE users")

        error_events = [e for e in events if e.is_error]
        assert len(error_events) >= 1
        assert error_events[0].data["kind"] == "guardrail_tripwire"


# ---------------------------------------------------------------------------
# Output guardrail blocks output
# ---------------------------------------------------------------------------


class TestOutputGuardrailBlocks:
    @pytest.mark.asyncio
    async def test_output_guardrail_blocks_secret_in_response(self) -> None:
        cfg = RuntimeConfig(
            runtime_name="thin",
            output_guardrails=[RegexGuardrail(patterns=[r"SECRET_\d+"])],
        )
        runtime = ThinRuntime(
            config=cfg,
            llm_call=_make_llm_call(SECRET_FINAL_JSON),
        )

        events = await _collect_events(runtime, user_text="tell me a secret")

        error_events = [e for e in events if e.is_error]
        assert len(error_events) >= 1
        assert error_events[0].data["kind"] == "guardrail_tripwire"

    @pytest.mark.asyncio
    async def test_output_guardrail_blocks_streaming_secret_before_any_delta(
        self,
    ) -> None:
        cfg = RuntimeConfig(
            runtime_name="thin",
            output_guardrails=[RegexGuardrail(patterns=[r"SECRET_\d+"])],
        )
        runtime = ThinRuntime(
            config=cfg,
            llm_call=_make_streaming_llm_call(
                [
                    '{"type":"final","final_message":"The SECRET_',
                    '123 is leaked"}',
                ],
                fallback_response=SECRET_FINAL_JSON,
            ),
        )

        events = await _collect_events(runtime, user_text="tell me a secret")

        assert not [e for e in events if e.type == "assistant_delta"]
        error_events = [e for e in events if e.is_error]
        assert len(error_events) == 1
        assert error_events[0].data["kind"] == "guardrail_tripwire"


# ---------------------------------------------------------------------------
# Multiple guardrails
# ---------------------------------------------------------------------------


class TestMultipleGuardrails:
    @pytest.mark.asyncio
    async def test_multiple_input_guardrails_all_pass(self) -> None:
        cfg = RuntimeConfig(
            runtime_name="thin",
            input_guardrails=[
                ContentLengthGuardrail(max_length=1000),
                RegexGuardrail(patterns=[r"DROP TABLE"]),
            ],
        )
        runtime = ThinRuntime(
            config=cfg,
            llm_call=_make_llm_call(VALID_FINAL_JSON),
        )

        events = await _collect_events(runtime, user_text="hello")

        final_events = [e for e in events if e.is_final]
        assert len(final_events) == 1
        assert final_events[0].data["text"] == "Hello, world!"


# ---------------------------------------------------------------------------
# Backward compat — no guardrails
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    @pytest.mark.asyncio
    async def test_no_guardrails_normal_flow(self) -> None:
        cfg = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(
            config=cfg,
            llm_call=_make_llm_call(VALID_FINAL_JSON),
        )

        events = await _collect_events(runtime, user_text="hello")

        error_events = [e for e in events if e.is_error]
        assert len(error_events) == 0

        final_events = [e for e in events if e.is_final]
        assert len(final_events) == 1
        assert final_events[0].data["text"] == "Hello, world!"
