"""Integration: Agent.query_structured() → ThinRuntime → Pydantic validation pipeline.

Tests the full path from Agent facade through ThinRuntime with a mock LLM,
verifying that structured output is parsed, validated, and returned as a
typed Pydantic model. Also tests retry on invalid JSON.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.structured import StructuredOutputError


# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------


class Sentiment(BaseModel):
    label: str
    score: float
    reasoning: str


class UserProfile(BaseModel):
    name: str
    age: int
    email: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_thin_agent(**overrides: Any) -> Agent:
    defaults: dict[str, Any] = {
        "system_prompt": "You are a helpful assistant.",
        "runtime": "thin",
    }
    defaults.update(overrides)
    return Agent(AgentConfig(**defaults))


# ---------------------------------------------------------------------------
# Full pipeline: Agent.query_structured() → ThinRuntime → validated model
# ---------------------------------------------------------------------------


class TestAgentQueryStructuredIntegration:
    """Agent.query_structured() end-to-end with ThinRuntime and mock LLM."""

    async def test_full_pipeline_valid_json(self) -> None:
        """LLM returns valid JSON → query_structured returns Pydantic model."""
        valid_response = json.dumps(
            {
                "label": "positive",
                "score": 0.92,
                "reasoning": "The text expresses joy and excitement.",
            }
        )

        call_count = 0

        async def mock_llm(
            messages: list[dict[str, str]], system_prompt: str, **kw: Any
        ) -> str:
            nonlocal call_count
            call_count += 1
            return json.dumps({"type": "final", "final_message": valid_response})

        agent = _make_thin_agent()

        # Patch the runtime creation to inject mock LLM
        from unittest.mock import patch

        from swarmline.runtime.thin.runtime import ThinRuntime

        def patched_factory_create(
            self_factory: Any, config: Any, **kwargs: Any
        ) -> ThinRuntime:
            return ThinRuntime(config=config, llm_call=mock_llm)

        with patch(
            "swarmline.runtime.factory.RuntimeFactory.create", patched_factory_create
        ):
            result = await agent.query_structured(
                "Analyze sentiment: I love sunny days!",
                Sentiment,
            )

        assert isinstance(result, Sentiment)
        assert result.label == "positive"
        assert result.score == 0.92
        assert "joy" in result.reasoning
        assert call_count == 1

    async def test_full_pipeline_retry_on_invalid_json(self) -> None:
        """LLM returns invalid JSON first, valid on retry → succeeds."""
        valid_response = json.dumps(
            {"name": "Alice", "age": 30, "email": "alice@example.com"}
        )
        attempts: list[int] = []

        async def mock_llm(
            messages: list[dict[str, str]], system_prompt: str, **kw: Any
        ) -> str:
            attempts.append(1)
            if len(attempts) == 1:
                # First attempt: invalid JSON
                return json.dumps(
                    {"type": "final", "final_message": "Not valid JSON at all"}
                )
            # Retry: valid JSON
            return json.dumps({"type": "final", "final_message": valid_response})

        agent = _make_thin_agent()

        from unittest.mock import patch

        from swarmline.runtime.thin.runtime import ThinRuntime

        def patched_factory_create(
            self_factory: Any, config: Any, **kwargs: Any
        ) -> ThinRuntime:
            return ThinRuntime(config=config, llm_call=mock_llm)

        with patch(
            "swarmline.runtime.factory.RuntimeFactory.create", patched_factory_create
        ):
            result = await agent.query_structured("Get user profile", UserProfile)

        assert isinstance(result, UserProfile)
        assert result.name == "Alice"
        assert result.age == 30
        assert len(attempts) == 2  # initial + 1 retry

    async def test_full_pipeline_all_retries_exhausted(self) -> None:
        """LLM returns invalid JSON every time → StructuredOutputError."""

        async def mock_llm(
            messages: list[dict[str, str]], system_prompt: str, **kw: Any
        ) -> str:
            return json.dumps({"type": "final", "final_message": "always invalid"})

        agent = _make_thin_agent()

        from unittest.mock import patch

        from swarmline.runtime.thin.runtime import ThinRuntime

        def patched_factory_create(
            self_factory: Any, config: Any, **kwargs: Any
        ) -> ThinRuntime:
            return ThinRuntime(config=config, llm_call=mock_llm)

        with patch(
            "swarmline.runtime.factory.RuntimeFactory.create", patched_factory_create
        ):
            with pytest.raises(StructuredOutputError, match="Failed to parse"):
                await agent.query_structured("Get sentiment", Sentiment)

    async def test_backward_compatibility_query_still_returns_str(self) -> None:
        """Agent.query() (not query_structured) still returns text, not model."""
        valid_response = json.dumps({"label": "pos", "score": 0.5, "reasoning": "ok"})

        async def mock_llm(
            messages: list[dict[str, str]], system_prompt: str, **kw: Any
        ) -> str:
            return json.dumps({"type": "final", "final_message": valid_response})

        agent = _make_thin_agent()

        from unittest.mock import patch

        from swarmline.runtime.thin.runtime import ThinRuntime

        def patched_factory_create(
            self_factory: Any, config: Any, **kwargs: Any
        ) -> ThinRuntime:
            return ThinRuntime(config=config, llm_call=mock_llm)

        with patch(
            "swarmline.runtime.factory.RuntimeFactory.create", patched_factory_create
        ):
            result = await agent.query("Give me sentiment")

        # query() returns Result with text, no structured_output (no output_type set)
        assert result.ok
        assert isinstance(result.text, str)
        assert result.structured_output is None

    async def test_output_type_in_agent_config_directly(self) -> None:
        """AgentConfig with output_type set — query() also validates."""
        valid_response = json.dumps({"name": "Bob", "age": 25, "email": "bob@test.com"})

        async def mock_llm(
            messages: list[dict[str, str]], system_prompt: str, **kw: Any
        ) -> str:
            return json.dumps({"type": "final", "final_message": valid_response})

        agent = _make_thin_agent(output_type=UserProfile)

        from unittest.mock import patch

        from swarmline.runtime.thin.runtime import ThinRuntime

        def patched_factory_create(
            self_factory: Any, config: Any, **kwargs: Any
        ) -> ThinRuntime:
            return ThinRuntime(config=config, llm_call=mock_llm)

        with patch(
            "swarmline.runtime.factory.RuntimeFactory.create", patched_factory_create
        ):
            result = await agent.query("Get user")

        assert result.ok
        assert result.structured_output is not None
        assert isinstance(result.structured_output, UserProfile)
        assert result.structured_output.name == "Bob"
