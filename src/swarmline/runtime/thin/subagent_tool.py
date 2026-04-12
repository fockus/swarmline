"""Subagent tool: spawn_agent ToolSpec + executor for LLM-initiated subagents.

Provides SUBAGENT_TOOL_SPEC (the ToolSpec registered with the runtime)
and create_subagent_executor() which returns an async callable that the
ToolExecutor invokes when the LLM calls spawn_agent.

Design:
- max_depth guard prevents infinite recursion
- All errors → JSON, executor NEVER raises
- Tool inheritance: LLM selects tools by name from parent_tools
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from swarmline.domain_types import ToolSpec
from swarmline.orchestration.subagent_types import SubagentSpec


@dataclass(frozen=True)
class SubagentToolConfig:
    """Configuration for the spawn_agent tool."""

    max_concurrent: int = 4
    max_depth: int = 3
    timeout_seconds: float = 300.0


SUBAGENT_TOOL_SPEC = ToolSpec(
    name="spawn_agent",
    description="Spawn a child agent to execute a subtask",
    parameters={
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task for the child agent to execute",
            },
            "system_prompt": {
                "type": "string",
                "description": "System prompt for the child agent",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names the child agent can use (defaults to all parent tools)",
            },
        },
        "required": ["task"],
    },
    is_local=True,
)


def _json_error(error: str, agent_id: str | None = None) -> str:
    """Build a JSON error response."""
    payload: dict[str, Any] = {"status": "error", "error": error}
    if agent_id is not None:
        payload["agent_id"] = agent_id
    return json.dumps(payload)


def create_subagent_executor(
    orchestrator: Any,
    config: SubagentToolConfig,
    parent_tools: list[ToolSpec],
    current_depth: int = 0,
) -> Callable[[dict[str, Any]], Coroutine[Any, Any, str]]:
    """Create an async callable that spawns a child agent via the orchestrator.

    Args:
        orchestrator: ThinSubagentOrchestrator (or compatible duck-type).
        config: SubagentToolConfig with limits.
        parent_tools: Tools available to the parent — child inherits a subset.
        current_depth: Current recursion depth (0 = top-level agent).

    Returns:
        Async callable(args: dict) -> str (always valid JSON, never raises).
    """
    tools_by_name: dict[str, ToolSpec] = {t.name: t for t in parent_tools}

    async def _execute(args: dict[str, Any]) -> str:
        agent_id: str | None = None
        try:
            # --- depth guard ---
            if current_depth >= config.max_depth:
                return _json_error(
                    f"Maximum subagent depth ({config.max_depth}) exceeded. "
                    f"Current depth: {current_depth}."
                )

            # --- validate task ---
            task = args.get("task")
            if not task or not str(task).strip():
                return _json_error("Missing required argument: 'task' must be a non-empty string.")

            task = str(task).strip()
            system_prompt = str(args.get("system_prompt", "You are a helpful assistant")).strip()

            # --- resolve tools ---
            requested_names: list[str] | None = args.get("tools")
            if requested_names is not None:
                child_tools = [tools_by_name[n] for n in requested_names if n in tools_by_name]
            else:
                child_tools = list(parent_tools)

            # --- build spec & spawn ---
            spec = SubagentSpec(
                name=f"subagent-depth-{current_depth + 1}",
                system_prompt=system_prompt,
                tools=child_tools,
            )
            agent_id = await orchestrator.spawn(spec, task)

            # --- wait with timeout ---
            result = await asyncio.wait_for(
                orchestrator.wait(agent_id),
                timeout=config.timeout_seconds,
            )

            # --- map result to JSON ---
            state = result.status.state
            if state == "failed":
                return json.dumps({
                    "agent_id": result.agent_id,
                    "status": "failed",
                    "error": result.status.error or "Unknown error",
                })

            return json.dumps({
                "agent_id": result.agent_id,
                "status": "completed",
                "result": result.output,
            })

        except asyncio.TimeoutError:
            if agent_id is not None:
                await orchestrator.cancel(agent_id)
            return _json_error(
                f"Timeout: subagent did not complete within {config.timeout_seconds}s.",
                agent_id=agent_id,
            )
        except Exception as exc:
            return _json_error(str(exc), agent_id=agent_id)

    return _execute
