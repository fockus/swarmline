"""Unit: Agent.query_structured() — type-safe structured output via Pydantic models.

Tests the Agent facade method that returns validated Pydantic models
instead of raw text, with automatic retry on validation errors.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.result import Result
from swarmline.agent.structured import StructuredOutputError


# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------


class Sentiment(BaseModel):
    label: str
    score: float
    reasoning: str


class SimpleModel(BaseModel):
    name: str
    age: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any) -> AgentConfig:
    defaults = {"system_prompt": "test prompt", "runtime": "thin"}
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_agent(**overrides: Any) -> Agent:
    return Agent(_make_config(**overrides))


# ---------------------------------------------------------------------------
# query_structured() — success path
# ---------------------------------------------------------------------------


class TestQueryStructuredSuccess:
    """query_structured() returns a validated Pydantic model on success."""

    async def test_returns_validated_model(self) -> None:
        """When runtime returns valid structured_output, it is returned directly."""
        agent = _make_agent()
        sentiment = Sentiment(label="positive", score=0.95, reasoning="Great!")

        async def _fake_query(prompt: str, config: AgentConfig) -> Result:
            return Result(
                text='{"label": "positive", "score": 0.95, "reasoning": "Great!"}',
                structured_output=sentiment,
            )

        with patch.object(agent, "_query_with_config", side_effect=_fake_query):
            result = await agent.query_structured("Analyze this", Sentiment)

        assert isinstance(result, Sentiment)
        assert result.label == "positive"
        assert result.score == 0.95

    async def test_returns_correct_type(self) -> None:
        """Return type matches the requested output_type."""
        agent = _make_agent()
        model = SimpleModel(name="Alice", age=30)

        async def _fake_query(prompt: str, config: AgentConfig) -> Result:
            return Result(text='{"name": "Alice", "age": 30}', structured_output=model)

        with patch.object(agent, "_query_with_config", side_effect=_fake_query):
            result = await agent.query_structured("Get user", SimpleModel)

        assert isinstance(result, SimpleModel)
        assert result.name == "Alice"
        assert result.age == 30

    async def test_passes_prompt_through(self) -> None:
        """The original prompt is passed to query()."""
        agent = _make_agent()
        captured_prompts: list[str] = []

        async def _fake_query(prompt: str, config: AgentConfig) -> Result:
            captured_prompts.append(prompt)
            return Result(
                text='{"name": "Bob", "age": 25}',
                structured_output=SimpleModel(name="Bob", age=25),
            )

        with patch.object(agent, "_query_with_config", side_effect=_fake_query):
            await agent.query_structured("Find Bob", SimpleModel)

        assert captured_prompts == ["Find Bob"]


# ---------------------------------------------------------------------------
# query_structured() — error path
# ---------------------------------------------------------------------------


class TestQueryStructuredError:
    """query_structured() raises StructuredOutputError when validation fails."""

    async def test_raises_on_no_structured_output(self) -> None:
        """When Result.structured_output is None, raises StructuredOutputError."""
        agent = _make_agent()

        async def _fake_query(prompt: str, config: AgentConfig) -> Result:
            return Result(text="Not JSON at all", structured_output=None)

        with patch.object(agent, "_query_with_config", side_effect=_fake_query):
            with pytest.raises(StructuredOutputError, match="Failed to parse"):
                await agent.query_structured("Analyze this", Sentiment)

    async def test_error_contains_raw_text_excerpt(self) -> None:
        """StructuredOutputError message includes raw text excerpt."""
        agent = _make_agent()

        async def _fake_query(prompt: str, config: AgentConfig) -> Result:
            return Result(text="This is not valid JSON", structured_output=None)

        with patch.object(agent, "_query_with_config", side_effect=_fake_query):
            with pytest.raises(StructuredOutputError, match="This is not valid JSON"):
                await agent.query_structured("Test", Sentiment)

    async def test_error_contains_type_name(self) -> None:
        """StructuredOutputError mentions the expected type name."""
        agent = _make_agent()

        async def _fake_query(prompt: str, config: AgentConfig) -> Result:
            return Result(text="bad", structured_output=None)

        with patch.object(agent, "_query_with_config", side_effect=_fake_query):
            with pytest.raises(StructuredOutputError, match="Sentiment"):
                await agent.query_structured("Test", Sentiment)


# ---------------------------------------------------------------------------
# query_structured() — config propagation
# ---------------------------------------------------------------------------


class TestQueryStructuredConfigPropagation:
    """query_structured() correctly sets output_type on the temporary config."""

    async def test_sets_output_type_on_config(self) -> None:
        """Per-call config has output_type set to the requested Pydantic model."""
        agent = _make_agent()
        captured_configs: list[AgentConfig] = []

        async def _spy_query(prompt: str, config: AgentConfig) -> Result:
            captured_configs.append(config)
            return Result(
                text='{"name": "X", "age": 1}',
                structured_output=SimpleModel(name="X", age=1),
            )

        with patch.object(agent, "_query_with_config", side_effect=_spy_query):
            await agent.query_structured("Test", SimpleModel)

        assert len(captured_configs) == 1
        assert captured_configs[0].output_type is SimpleModel

    async def test_sets_output_format_from_schema(self) -> None:
        """When output_format is None, it is auto-generated from model schema."""
        agent = _make_agent()
        captured_configs: list[AgentConfig] = []

        async def _spy_query(prompt: str, config: AgentConfig) -> Result:
            captured_configs.append(config)
            return Result(
                text='{"name": "X", "age": 1}',
                structured_output=SimpleModel(name="X", age=1),
            )

        with patch.object(agent, "_query_with_config", side_effect=_spy_query):
            await agent.query_structured("Test", SimpleModel)

        config = captured_configs[0]
        assert config.output_format is not None
        assert "properties" in config.output_format

    async def test_sets_structured_mode_and_retry_override(self) -> None:
        """query_structured() forwards structured mode and retry override."""
        agent = _make_agent()
        captured_configs: list[AgentConfig] = []

        async def _spy_query(prompt: str, config: AgentConfig) -> Result:
            captured_configs.append(config)
            return Result(
                text='{"name": "X", "age": 1}',
                structured_output=SimpleModel(name="X", age=1),
            )

        with patch.object(agent, "_query_with_config", side_effect=_spy_query):
            await agent.query_structured(
                "Test",
                SimpleModel,
                structured_mode="native",
                max_retries=5,
            )

        config = captured_configs[0]
        assert config.structured_mode == "native"
        assert config.max_model_retries == 5

    async def test_restores_original_config_after_success(self) -> None:
        """After query_structured(), the agent config is restored."""
        agent = _make_agent()
        original_config = agent._config

        async def _fake_query(prompt: str, config: AgentConfig) -> Result:
            return Result(
                text='{"name": "X", "age": 1}',
                structured_output=SimpleModel(name="X", age=1),
            )

        with patch.object(agent, "_query_with_config", side_effect=_fake_query):
            await agent.query_structured("Test", SimpleModel)

        assert agent._config is original_config
        assert agent._config.output_type is None

    async def test_restores_original_config_after_error(self) -> None:
        """Config is restored even when query_structured raises."""
        agent = _make_agent()
        original_config = agent._config

        async def _failing_query(prompt: str, config: AgentConfig) -> Result:
            return Result(text="bad", structured_output=None)

        with patch.object(agent, "_query_with_config", side_effect=_failing_query):
            with pytest.raises(StructuredOutputError):
                await agent.query_structured("Test", Sentiment)

        assert agent._config is original_config

    async def test_preserves_existing_output_format(self) -> None:
        """If output_format is already set, it is not overwritten."""
        custom_format = {"type": "object", "properties": {"x": {"type": "string"}}}
        agent = _make_agent(output_format=custom_format)

        async def _spy_query(prompt: str, config: AgentConfig) -> Result:
            # The config should keep the original output_format
            assert config.output_format == custom_format
            return Result(
                text='{"name": "X", "age": 1}',
                structured_output=SimpleModel(name="X", age=1),
            )

        with patch.object(agent, "_query_with_config", side_effect=_spy_query):
            await agent.query_structured("Test", SimpleModel)

    async def test_concurrent_calls_use_isolated_configs(self) -> None:
        """Concurrent structured requests must not race through shared Agent._config."""
        agent = _make_agent()
        seen_output_types: list[type[Any]] = []
        release = asyncio.Event()

        class OtherModel(BaseModel):
            flag: bool

        async def _spy_query(prompt: str, config: AgentConfig) -> Result:
            seen_output_types.append(config.output_type)
            if len(seen_output_types) == 2:
                release.set()
            await release.wait()
            if config.output_type is SimpleModel:
                return Result(
                    text='{"name":"A","age":1}',
                    structured_output=SimpleModel(name="A", age=1),
                )
            return Result(
                text='{"flag": true}',
                structured_output=OtherModel(flag=True),
            )

        with patch.object(agent, "_query_with_config", side_effect=_spy_query):
            simple_task = asyncio.create_task(
                agent.query_structured("simple", SimpleModel)
            )
            other_task = asyncio.create_task(
                agent.query_structured("other", OtherModel)
            )
            simple_result, other_result = await asyncio.gather(simple_task, other_task)

        assert set(seen_output_types) == {SimpleModel, OtherModel}
        assert simple_result.name == "A"
        assert other_result.flag is True
        assert agent.config.output_type is None


# ---------------------------------------------------------------------------
# StructuredOutputError
# ---------------------------------------------------------------------------


class TestStructuredOutputError:
    """StructuredOutputError attributes and behavior."""

    def test_is_exception(self) -> None:
        err = StructuredOutputError("test")
        assert isinstance(err, Exception)

    def test_stores_raw_text(self) -> None:
        err = StructuredOutputError("msg", raw_text="some text")
        assert err.raw_text == "some text"

    def test_stores_output_type_name(self) -> None:
        err = StructuredOutputError("msg", output_type_name="MyModel")
        assert err.output_type_name == "MyModel"

    def test_str_representation(self) -> None:
        err = StructuredOutputError("Failed to parse output")
        assert "Failed to parse" in str(err)

    def test_importable_from_agent_package(self) -> None:
        from swarmline.agent import StructuredOutputError as Imported

        assert Imported is StructuredOutputError
