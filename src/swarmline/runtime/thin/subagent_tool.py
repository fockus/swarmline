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
from swarmline.tools.types import SandboxConfig


@dataclass(frozen=True)
class SubagentToolConfig:
    """Configuration for the spawn_agent tool."""

    max_concurrent: int = 4
    max_worktrees: int = 5
    max_depth: int = 3
    timeout_seconds: float = 300.0
    base_path: str | None = None
    background_timeout: float | None = None
    sandbox_config: SandboxConfig | None = None


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
            "isolation": {
                "type": "string",
                "enum": ["worktree"],
                "description": "Isolation mode for child agent. 'worktree' runs in a dedicated git worktree.",
            },
            "run_in_background": {
                "type": "boolean",
                "description": "If true, spawn agent in background and return immediately with agent_id.",
            },
        },
        "required": ["task"],
    },
    is_local=True,
)


MONITOR_AGENT_TOOL_SPEC = ToolSpec(
    name="monitor_agent",
    description="Check status and retrieve output of a background agent",
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "The agent_id returned by spawn_agent with run_in_background=true",
            },
        },
        "required": ["agent_id"],
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
                return _json_error(
                    "Missing required argument: 'task' must be a non-empty string."
                )

            task = str(task).strip()
            system_prompt = str(
                args.get("system_prompt", "You are a helpful assistant")
            ).strip()

            # --- resolve tools ---
            requested_names: list[str] | None = args.get("tools")
            if requested_names is not None:
                child_tools = [
                    tools_by_name[n] for n in requested_names if n in tools_by_name
                ]
            else:
                child_tools = list(parent_tools)

            # --- isolation mode (optional) ---
            isolation: str | None = args.get("isolation")

            # --- run_in_background flag ---
            run_in_background: bool = bool(args.get("run_in_background", False))

            # --- build spec & spawn ---
            spec_kwargs: dict[str, Any] = {
                "name": f"subagent-depth-{current_depth + 1}",
                "system_prompt": system_prompt,
                "tools": child_tools,
            }
            if isolation is not None:
                spec_kwargs["isolation"] = isolation
            if run_in_background:
                spec_kwargs["run_in_background"] = True
            if config.sandbox_config is not None:
                spec_kwargs["sandbox_config"] = config.sandbox_config
            spec = SubagentSpec(**spec_kwargs)
            agent_id = await orchestrator.spawn(spec, task)

            # --- background: return immediately ---
            if run_in_background:
                return json.dumps(
                    {
                        "agent_id": agent_id,
                        "status": "spawned",
                        "message": "Agent spawned in background. Use monitor_agent to check status.",
                    }
                )

            # --- foreground: wait with timeout ---
            result = await asyncio.wait_for(
                orchestrator.wait(agent_id),
                timeout=config.timeout_seconds,
            )

            # --- map result to JSON ---
            state = result.status.state
            if state == "failed":
                return json.dumps(
                    {
                        "agent_id": result.agent_id,
                        "status": "failed",
                        "error": result.status.error or "Unknown error",
                    }
                )

            return json.dumps(
                {
                    "agent_id": result.agent_id,
                    "status": "completed",
                    "result": result.output,
                }
            )

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


def create_monitor_executor(
    orchestrator: Any,
) -> Callable[[dict[str, Any]], Coroutine[Any, Any, str]]:
    """Create the monitor_agent tool executor.

    Checks status and retrieves output of a background agent
    via MONITOR_AGENT_TOOL_SPEC.

    Args:
        orchestrator: ThinSubagentOrchestrator (or compatible duck-type).

    Returns:
        Async callable(args: dict) -> str (always valid JSON, never raises).
    """

    async def _execute(args: dict[str, Any]) -> str:
        try:
            agent_id = args.get("agent_id")
            if not agent_id or not str(agent_id).strip():
                return _json_error(
                    "Missing required argument: 'agent_id' must be a non-empty string."
                )

            agent_id = str(agent_id).strip()
            status = await orchestrator.get_status(agent_id)
            output = orchestrator.get_output(agent_id)

            payload: dict[str, Any] = {
                "agent_id": agent_id,
                "state": status.state,
                "output": output,
            }
            if status.error is not None:
                payload["error"] = status.error
            if status.result is not None:
                payload["result"] = status.result

            return json.dumps(payload)
        except Exception as exc:
            return _json_error(str(exc))

    return _execute
