"""StatefulSession -- central state container for MCP server.

Manages all in-memory providers and the headless/full mode distinction.
State persists between MCP tool calls within a single server process.
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Any, Literal

import structlog

if TYPE_CHECKING:
    from swarmline.agent import Agent, Result

logger = structlog.get_logger(__name__)


class HeadlessModeError(Exception):
    """Raised when a full-mode operation is attempted in headless mode."""


class StatefulSession:
    """Manages all state between MCP tool calls.

    Headless mode (default): memory, plans, team coordination, code execution.
    Full mode: + agent creation/querying via user's API key.
    """

    def __init__(self, *, mode: Literal["headless", "full"] = "headless") -> None:
        from swarmline.memory.inmemory import InMemoryMemoryProvider
        from swarmline.multi_agent.agent_registry import InMemoryAgentRegistry
        from swarmline.multi_agent.task_queue import InMemoryTaskQueue
        from swarmline.orchestration.plan_store import InMemoryPlanStore

        self.mode = mode
        self.memory = InMemoryMemoryProvider()
        self.plan_store = InMemoryPlanStore()
        self.agent_registry = InMemoryAgentRegistry()
        self.task_queue = InMemoryTaskQueue()

        # Full mode: track created agents and conversations
        self._agents: dict[str, Agent] = {}
        self._agent_configs: dict[str, dict[str, Any]] = {}

        logger.info("session_created", mode=mode)

    def require_full_mode(self) -> None:
        """Raise HeadlessModeError if not in full mode."""
        if self.mode != "full":
            raise HeadlessModeError(
                "This operation requires full mode. "
                "Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable, "
                "then start the server with: swarmline-mcp full"
            )

    async def create_agent(
        self,
        system_prompt: str,
        model: str = "sonnet",
        runtime: str = "thin",
        max_turns: int | None = None,
    ) -> str:
        """Create an agent and return its ID. Full mode only."""
        self.require_full_mode()

        from swarmline.agent import Agent, AgentConfig

        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        config = AgentConfig(
            system_prompt=system_prompt,
            model=model,
            runtime=runtime,
            max_turns=max_turns,
        )
        agent = Agent(config)
        self._agents[agent_id] = agent
        self._agent_configs[agent_id] = {
            "system_prompt": system_prompt,
            "model": model,
            "runtime": runtime,
        }
        logger.info("agent_created", agent_id=agent_id, model=model, runtime=runtime)
        return agent_id

    async def query_agent(self, agent_id: str, prompt: str) -> Result:
        """Query an existing agent. Full mode only."""
        self.require_full_mode()

        if agent_id not in self._agents:
            raise KeyError(f"Agent not found: {agent_id}")

        agent = self._agents[agent_id]
        result = await agent.query(prompt)
        logger.info(
            "agent_queried",
            agent_id=agent_id,
            ok=result.ok,
            text_length=len(result.text) if result.text else 0,
        )
        return result

    def list_agents(self) -> list[dict[str, Any]]:
        """List all created agents with their configs."""
        return [
            {"agent_id": aid, **self._agent_configs.get(aid, {})}
            for aid in self._agents
        ]

    async def cleanup(self) -> None:
        """Clean up all agents and resources."""
        for agent_id, agent in self._agents.items():
            try:
                await agent.cleanup()
            except Exception:
                logger.warning("agent_cleanup_failed", agent_id=agent_id, exc_info=True)
        self._agents.clear()
        self._agent_configs.clear()
        logger.info("session_cleanup_complete")


def resolve_mode(mode: str) -> Literal["headless", "full"]:
    """Resolve server mode from argument or environment.

    'auto' checks for API keys in environment.
    """
    if mode == "full":
        return "full"
    if mode == "headless":
        return "headless"
    # Auto-detect
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return "full"
    return "headless"
