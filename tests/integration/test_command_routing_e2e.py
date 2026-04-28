"""Integration tests for command routing through Agent facade.

Verifies the full path: Agent(command_registry=...) -> query("/help")
intercepts and returns command result without calling LLM.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.commands.registry import CommandRegistry
import pytest

pytestmark = pytest.mark.integration


def _make_registry() -> CommandRegistry:
    registry = CommandRegistry()

    async def help_handler(*args: Any, **kwargs: Any) -> str:
        return "Available commands: /help, /topic.new"

    registry.add("help", handler=help_handler, description="Show help")
    return registry


class TestCommandRoutingE2E:
    """Full Agent -> ThinRuntime command routing integration."""

    async def test_agent_query_with_command(self) -> None:
        """Agent with CommandRegistry: query('/help') returns command result, no LLM call."""
        registry = _make_registry()
        config = AgentConfig(
            system_prompt="You are a helpful assistant.",
            runtime="thin",
            command_registry=registry,
        )
        agent = Agent(config)

        result = await agent.query("/help")

        assert "Available commands:" in result.text
        assert "/help" in result.text

    async def test_agent_query_without_registry(self) -> None:
        """Agent without registry: query('hello') goes to LLM path (mocked)."""
        config = AgentConfig(
            system_prompt="You are a helpful assistant.",
            runtime="thin",
        )
        agent = Agent(config)

        # Mock the LLM call to avoid real API calls
        fake_response = json.dumps(
            {"type": "final", "final_message": "Hello! How can I help?"}
        )

        async def fake_llm(messages: Any, system_prompt: str, **kwargs: Any) -> str:
            return fake_response

        # Patch at ThinRuntime level to inject fake LLM
        with patch(
            "swarmline.runtime.thin.runtime.ThinRuntime._make_default_llm_call",
            return_value=fake_llm,
        ):
            result = await agent.query("hello")

        assert result.text == "Hello! How can I help?"
