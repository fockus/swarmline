"""Unit tests for provider-native structured request planning."""

from __future__ import annotations

from pydantic import BaseModel, Field

from swarmline.runtime.structured_requests import (
    build_llm_call_kwargs,
    resolve_structured_request_strategy,
)
from swarmline.runtime.types import ModelRequestOptions, RuntimeConfig


class DemoResponse(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    summary: str = Field(min_length=3)


def test_resolve_structured_request_strategy_openrouter_native_json_schema() -> None:
    cfg = RuntimeConfig(
        runtime_name="thin",
        model="openrouter:openai/gpt-oss-120b",
        output_type=DemoResponse,
        structured_mode="native",
    )

    strategy = resolve_structured_request_strategy(cfg)

    assert strategy.mode == "native_json_schema"
    assert strategy.provider == "openrouter"


def test_resolve_structured_request_strategy_deepseek_uses_json_object() -> None:
    cfg = RuntimeConfig(
        runtime_name="thin",
        model="deepseek:deepseek-chat",
        output_type=DemoResponse,
        structured_mode="native",
    )

    strategy = resolve_structured_request_strategy(cfg)

    assert strategy.mode == "native_json_object"
    assert strategy.provider == "deepseek"


def test_resolve_structured_request_strategy_auto_falls_back_to_prompt() -> None:
    cfg = RuntimeConfig(
        runtime_name="thin",
        model="anthropic:claude-sonnet-4-20250514",
        output_type=DemoResponse,
        structured_mode="auto",
    )

    strategy = resolve_structured_request_strategy(cfg)

    assert strategy.mode == "prompt"
    assert strategy.provider == "anthropic"


def test_build_llm_call_kwargs_adds_openrouter_native_schema_options() -> None:
    cfg = RuntimeConfig(
        runtime_name="thin",
        model="openrouter:openai/gpt-oss-120b",
        output_type=DemoResponse,
        structured_mode="native",
        structured_schema_name="demo_response_v1",
        request_options=ModelRequestOptions(max_tokens=321, temperature=0.1),
    )

    kwargs = build_llm_call_kwargs(cfg)

    assert kwargs["max_tokens"] == 321
    assert kwargs["temperature"] == 0.1
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["response_format"]["json_schema"]["name"] == "demo_response_v1"
    assert "minimum" not in str(kwargs["response_format"])
    assert "minLength" not in str(kwargs["response_format"])
    assert kwargs["extra_body"]["provider"] == {"require_parameters": True}
