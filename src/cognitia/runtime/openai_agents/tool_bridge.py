"""Bridge Cognitia ToolSpec to OpenAI Agents SDK FunctionTool."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from cognitia.runtime.types import ToolSpec

_log = structlog.get_logger(component="openai_agents_tool_bridge")

# Type for the executor callback: (tool_name, kwargs) -> result_str
ToolExecutorFn = Callable[[str, dict[str, Any]], Awaitable[str]]


def toolspec_to_function_tool(
    spec: ToolSpec,
    executor: ToolExecutorFn | None = None,
) -> Any:
    """Convert a Cognitia ToolSpec to an OpenAI Agents SDK FunctionTool.

    Args:
        spec: Cognitia tool specification.
        executor: Async callback that executes the tool and returns result string.
            Signature: ``async def executor(tool_name: str, kwargs: dict) -> str``.
            If None, tool returns an error indicating no executor is configured.
    """
    from agents import FunctionTool

    tool_name = spec.name
    tool_executor = executor

    async def _on_invoke(ctx: Any, args: str) -> str:
        try:
            parsed = json.loads(args) if args else {}
        except json.JSONDecodeError:
            _log.warning("tool_invalid_json_args", tool=tool_name, args_preview=args[:200])
            return json.dumps({"error": f"Invalid JSON arguments for tool '{tool_name}'"})
        if tool_executor is None:
            _log.warning("tool_no_executor", tool=tool_name)
            return json.dumps({"error": f"No executor configured for tool '{tool_name}'"})
        return await tool_executor(tool_name, parsed)

    params_schema = spec.parameters or {"type": "object", "properties": {}}
    # OpenAI strict mode rejects additionalProperties
    clean_schema = {k: v for k, v in params_schema.items() if k != "additionalProperties"}

    return FunctionTool(
        name=tool_name,
        description=spec.description,
        params_json_schema=clean_schema,
        on_invoke_tool=_on_invoke,
    )


def toolspecs_to_agent_tools(
    specs: list[ToolSpec],
    executor: ToolExecutorFn | None = None,
) -> list[Any]:
    """Convert a list of Cognitia ToolSpecs to OpenAI Agent tools.

    Args:
        specs: List of tool specs. Only local tools (is_local=True) are converted.
        executor: Shared executor callback for all tools.
    """
    return [
        toolspec_to_function_tool(spec, executor=executor)
        for spec in specs
        if spec.is_local
    ]
