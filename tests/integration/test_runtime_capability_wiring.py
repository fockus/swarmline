"""Integration: runtime capability negotiation and fail-fast wiring."""

from __future__ import annotations

import pytest
from cognitia.agent import Agent, AgentConfig
from cognitia.runtime.capabilities import CapabilityRequirements
from cognitia.runtime.factory import RuntimeFactory
from cognitia.runtime.types import RuntimeConfig


class TestRuntimeCapabilityNegotiation:
    """RuntimeFactory and Agent wiring for capability-aware selectiona runtime."""

    @pytest.mark.asyncio
    async def test_runtime_selection_fail_fast_on_missing_capability(self) -> None:
        """override -> unsupported runtime returns typed capability error event."""
        factory = RuntimeFactory()
        config = RuntimeConfig(
            runtime_name="claude_sdk",
            required_capabilities=CapabilityRequirements(tier="full"),
        )

        runtime = factory.create(config=config, runtime_override="thin")

        events = []
        async for event in runtime.run():
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].data["kind"] == "capability_unsupported"
        assert "tier:full" in events[0].data["details"]["missing"]

    def test_agent_exposes_capability_descriptor(self) -> None:
        """Agent daet prilozheniyu capability descriptor vybrannogo runtime."""
        agent = Agent(
            AgentConfig(
                system_prompt="test",
                runtime="deepagents",
                require_capabilities=CapabilityRequirements(tier="full"),
            )
        )

        caps = agent.runtime_capabilities
        assert caps.runtime_name == "deepagents"
        assert caps.tier == "full"
