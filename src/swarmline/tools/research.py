"""spawn_research tool — spawns a research sub-agent via SubagentOrchestrator.

Creates a focused research sub-agent that investigates a query and returns findings.
Follows the same tool pattern as builtin.py (ToolSpec + executor callable).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from swarmline.orchestration.context_bridge import ContextBridge
from swarmline.orchestration.subagent_protocol import SubagentOrchestrator
from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.runtime.types import ToolSpec

_SPAWN_RESEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Research question or topic to investigate",
        },
        "context": {
            "type": "string",
            "description": "Additional context from the current task (optional)",
            "default": "",
        },
        "max_turns": {
            "type": "integer",
            "description": "Maximum turns for the research sub-agent",
            "default": 5,
        },
    },
    "required": ["query"],
}

_RESEARCH_SYSTEM_PROMPT_TEMPLATE = (
    "You are a research sub-agent. "
    "Your goal: find information about {query}.\n"
    "{context_section}"
    "Report your findings clearly and concisely."
)


def _build_research_prompt(query: str, context: str) -> str:
    """Build research-focused system prompt."""
    context_section = f"Context from parent: {context}\n" if context else ""
    return _RESEARCH_SYSTEM_PROMPT_TEMPLATE.format(
        query=query,
        context_section=context_section,
    )


def make_spawn_research_tool(
    orchestrator: SubagentOrchestrator,
    context_bridge: ContextBridge | None = None,
) -> tuple[ToolSpec, Callable[..., Any]]:
    """Factory: create spawn_research ToolSpec + executor bound to an orchestrator.

    Args:
        orchestrator: SubagentOrchestrator instance for spawning sub-agents.
        context_bridge: Optional ContextBridge to pass parent context to sub-agent.

    Returns:
        Tuple of (ToolSpec, async executor callable).
    """

    async def executor(args: dict[str, Any]) -> str:
        query = args.get("query", "")
        if not query or not query.strip():
            return json.dumps({"status": "error", "message": "query is required"})

        context = args.get("context", "")
        system_prompt = _build_research_prompt(query.strip(), context)

        # Override max_turns in context bridge only if explicitly provided
        effective_bridge = context_bridge
        if "max_turns" in args and effective_bridge is not None:
            from dataclasses import replace

            capped_turns = min(max(int(args["max_turns"]), 1), 50)
            effective_bridge = replace(effective_bridge, max_turns=capped_turns)

        spec = SubagentSpec(
            name="research",
            system_prompt=system_prompt,
            context_bridge=effective_bridge,
        )

        try:
            agent_id = await orchestrator.spawn(spec, query)
            result = await orchestrator.wait(agent_id)
            return json.dumps(
                {"status": "ok", "output": result.output, "agent_id": agent_id}
            )
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    tool_spec = ToolSpec(
        name="spawn_research",
        description="Spawn a research sub-agent to investigate a topic",
        parameters=_SPAWN_RESEARCH_SCHEMA,
    )

    return tool_spec, executor
