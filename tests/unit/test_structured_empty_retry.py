"""Retry-on-empty for structured output (universal, provider-agnostic, opt-in).

`finalize_with_validation` already retries when structured output fails to parse/validate. These
tests pin the new behaviour: a schema-valid but SEMANTICALLY EMPTY result — one that opts into the
`is_empty_result()` protocol and reports True — is the same retryable miss as a parse failure. It is
re-asked within the existing `max_model_retries` budget, then surfaced as a `bad_model_output` error
instead of a silently-empty success. Schemas WITHOUT the protocol behave byte-for-byte as before.

No network: a recording async `llm_call` stands in for the provider.
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel

from swarmline.runtime.structured_output import empty_result_error
from swarmline.runtime.thin.finalization import finalize_with_validation
from swarmline.runtime.types import RuntimeConfig


class _Selection(BaseModel):
    """Empty-aware schema: an empty `picks` list is a degenerate provider miss."""

    picks: list[int] = []

    def is_empty_result(self) -> bool:
        return not self.picks


class _Plain(BaseModel):
    """No `is_empty_result` → never participates in empty-retry (back-compat shape)."""

    answer: str = ""


class _Exploding(BaseModel):
    answer: str = ""

    def is_empty_result(self) -> bool:
        raise RuntimeError("predicate blew up")


# --- pure helper -------------------------------------------------------------------------------


def test_empty_result_error_returns_none_for_model_without_predicate() -> None:
    assert empty_result_error(_Plain(answer="hi")) is None


def test_empty_result_error_returns_message_when_predicate_true() -> None:
    msg = empty_result_error(_Selection(picks=[]))
    assert msg is not None and isinstance(msg, str) and msg


def test_empty_result_error_returns_none_when_predicate_false() -> None:
    assert empty_result_error(_Selection(picks=[1, 2])) is None


def test_empty_result_error_swallows_predicate_exception() -> None:
    # A buggy predicate must never break finalization → treated as "not empty".
    assert empty_result_error(_Exploding()) is None


# --- finalization loop -------------------------------------------------------------------------


def _config(output_type: type[BaseModel], retries: int = 2) -> RuntimeConfig:
    return RuntimeConfig(
        model="gpt-4o",
        output_type=output_type,
        output_format=output_type.model_json_schema(),
        max_model_retries=retries,
    )


async def _drain(agen) -> list:
    return [event async for event in agen]


@pytest.mark.asyncio
async def test_finalize_retries_on_empty_then_succeeds() -> None:
    calls: list = []

    async def llm_call(messages, prompt, **kwargs):
        calls.append(messages)
        return '{"picks": [1, 2]}'  # the retry yields a non-empty selection

    events = await _drain(
        finalize_with_validation(
            text='{"picks": []}',  # phase-1: schema-valid but EMPTY
            config=_config(_Selection),
            lm_messages=[{"role": "user", "content": "pick"}],
            prompt="SYS",
            llm_call=llm_call,
            start_time=time.monotonic(),
        )
    )

    assert len(calls) == 1, "empty phase-1 result must trigger exactly one re-ask"
    final = events[-1]
    assert final.structured_output is not None
    assert final.structured_output.picks == [1, 2]

    # The empty path must re-ask with its OWN, empty-specific instruction
    # (`_EMPTY_RETRY_INSTRUCTION`), NOT the parse-failure one (`_RETRY_INSTRUCTION`,
    # "not valid JSON"). Without this, a regression that reuses `_RETRY_INSTRUCTION`
    # for the empty branch would pass unnoticed (calls/result stay the same).
    retry_messages = calls[0]
    last_user = next(m for m in reversed(retry_messages) if m["role"] == "user")
    instruction = last_user["content"]
    assert "semantically empty" in instruction, (
        "empty-retry must use the empty-specific instruction (_EMPTY_RETRY_INSTRUCTION)"
    )
    assert "not valid JSON" not in instruction, (
        "empty-retry must not fall back to the parse-failure text (_RETRY_INSTRUCTION)"
    )


@pytest.mark.asyncio
async def test_finalize_plain_schema_does_not_retry() -> None:
    calls: list = []

    async def llm_call(messages, prompt, **kwargs):
        calls.append(messages)
        return '{"answer": "x"}'

    events = await _drain(
        finalize_with_validation(
            text='{"answer": "done"}',  # valid; plain schema has no emptiness notion
            config=_config(_Plain),
            lm_messages=[{"role": "user", "content": "go"}],
            prompt="SYS",
            llm_call=llm_call,
            start_time=time.monotonic(),
        )
    )

    assert calls == [], (
        "schema without is_empty_result must never trigger an empty-retry"
    )
    assert events[-1].structured_output.answer == "done"


@pytest.mark.asyncio
async def test_finalize_empty_exhausts_to_bad_model_output() -> None:
    async def llm_call(messages, prompt, **kwargs):
        return '{"picks": []}'  # always empty → exhaust retries

    events = await _drain(
        finalize_with_validation(
            text='{"picks": []}',
            config=_config(_Selection, retries=2),
            lm_messages=[{"role": "user", "content": "pick"}],
            prompt="SYS",
            llm_call=llm_call,
            start_time=time.monotonic(),
        )
    )

    last = events[-1]
    assert last.is_error, "exhausting empty-retries must surface an error event"
    assert last.data["kind"] == "bad_model_output"
