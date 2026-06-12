"""PROMPT-mode structured calls must accept BARE schema JSON (no final_message envelope).

The prompt-mode instruction asks the model to wrap its answer in
``{"type": "final", "final_message": "<json>"}`` — but that envelope is a swarmline
convention, not a provider contract. deepseek-v4 / qwen-class models routinely answer with
the TARGET schema JSON directly; the old flow burned a SECOND LLM call and then hard-failed
("LLM returned invalid JSON after 2 attempts") even though the first answer was schema-valid.
Verified live against polza.ai (faberlic deep-search TurnDecision, 2026-06-12).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from swarmline.runtime.thin.conversational import run_conversational
from swarmline.runtime.thin.llm_client import LlmCallResult
from swarmline.runtime.types import RuntimeConfig


class _Decision(BaseModel):
    kind: str
    queries: list[str]


_BARE = '{"kind": "search", "queries": ["a", "b"]}'


def _config() -> RuntimeConfig:
    return RuntimeConfig(
        runtime_name="thin",
        model="deepseek/deepseek-v4-flash",
        output_type=_Decision,
        structured_mode="prompt",
    )


async def _events(mock_llm_call, config: RuntimeConfig):
    return [
        e async for e in run_conversational(mock_llm_call, [], "system", config, 0.0)
    ]


@pytest.mark.asyncio
async def test_bare_schema_json_resolves_structured_output() -> None:
    """A bare schema-valid JSON answer produces a final event with structured_output."""
    mock_llm_call = AsyncMock(side_effect=[LlmCallResult(text=_BARE), _BARE, _BARE])

    events = await _events(mock_llm_call, _config())

    finals = [e for e in events if e.type == "final"]
    assert finals, f"no final event; got {[e.type for e in events]}"
    out = finals[-1].data.get("structured_output")
    assert isinstance(out, _Decision)
    assert out.kind == "search"
    assert out.queries == ["a", "b"]


@pytest.mark.asyncio
async def test_bare_schema_json_needs_no_second_llm_call() -> None:
    """An already-valid bare answer must not burn a second LLM attempt."""
    mock_llm_call = AsyncMock(side_effect=[LlmCallResult(text=_BARE), _BARE, _BARE])

    await _events(mock_llm_call, _config())

    assert mock_llm_call.await_count == 1


@pytest.mark.asyncio
async def test_enveloped_answer_still_works() -> None:
    """REGRESSION: the documented envelope form keeps resolving exactly as before."""
    enveloped = json.dumps({"type": "final", "final_message": _BARE})
    mock_llm_call = AsyncMock(return_value=LlmCallResult(text=enveloped))

    events = await _events(mock_llm_call, _config())

    finals = [e for e in events if e.type == "final"]
    assert finals
    out = finals[-1].data.get("structured_output")
    assert isinstance(out, _Decision)
    assert out.kind == "search"


@pytest.mark.asyncio
async def test_invalid_bare_json_still_retries_then_errors() -> None:
    """A bare answer that does NOT validate keeps the retry-then-fail contract."""
    invalid = '{"unrelated": true}'
    mock_llm_call = AsyncMock(
        side_effect=[LlmCallResult(text=invalid), invalid, invalid, invalid]
    )

    events = await _events(mock_llm_call, _config())

    finals = [
        e for e in events if e.type == "final" and e.data.get("structured_output")
    ]
    assert not finals  # never a validated final from an invalid payload
    assert mock_llm_call.await_count >= 2  # the validation retry loop did run
