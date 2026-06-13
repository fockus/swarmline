"""native json_object structured calls MUST describe the schema IN THE PROMPT.

``response_format={"type": "json_object"}`` forces valid-JSON SYNTAX but the provider does NOT
enforce the schema SHAPE — without the schema in the prompt the model omits fields and a nested
list (e.g. ``picks``) parses to ``[]`` ("nothing found"). This is a universal swarmline fix: the
conversational strategy now injects the schema for json_object mode (not only prompt-mode). The
provider-enforced ``native_json_schema`` mode is left clean (no prompt text needed).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from swarmline.runtime.thin.conversational import run_conversational
from swarmline.runtime.thin.llm_client import LlmCallResult
from swarmline.runtime.types import RuntimeConfig


class _Decision(BaseModel):
    kind: str
    queries: list[str]


_VALID = '{"kind": "search", "queries": ["a", "b"]}'


async def _run_capture(model: str) -> str:
    """Run one conversational turn and return ALL text the runtime sent to the LLM."""
    config = RuntimeConfig(
        runtime_name="thin",
        model=model,
        output_type=_Decision,
        structured_mode="native",
    )
    mock_llm_call = AsyncMock(side_effect=[LlmCallResult(text=_VALID), _VALID, _VALID])

    _ = [e async for e in run_conversational(mock_llm_call, [], "system", config, 0.0)]

    parts: list[str] = []
    for call in mock_llm_call.await_args_list:
        parts.extend(str(a) for a in call.args)
        parts.extend(str(v) for v in call.kwargs.values())
    return " ".join(parts)


@pytest.mark.asyncio
async def test_json_object_mode_injects_schema_into_prompt() -> None:
    """deepseek (json_object provider) → the prompt carries the schema + field names."""
    sent = await _run_capture("deepseek:deepseek-chat")

    assert "Structured output" in sent
    assert '"queries"' in sent  # the schema's field reached the model


@pytest.mark.asyncio
async def test_json_schema_mode_leaves_prompt_clean() -> None:
    """openrouter (json_schema provider enforces the schema) → no in-prompt schema text."""
    sent = await _run_capture("openrouter:openai/gpt-oss-120b")

    assert "## Structured output" not in sent
