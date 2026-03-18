"""Built-in tools for ThinRuntime - port of DeepAgents native tools.

Provides 9 tools (read_file, write_file, edit_file, ls, glob, grep,
execute, write_todos, task) backed by SandboxProvider executors from
cognitia.tools.builtin. Supports feature_mode filtering (portable/hybrid/
native_first) and DeepAgents-compatible aliases.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from cognitia.runtime.builtin_names import BUILTIN_ALIASES, BUILTIN_TOOL_NAMES
from cognitia.runtime.types import ToolSpec
from cognitia.tools.builtin import create_sandbox_tools
from cognitia.tools.protocols import SandboxProvider

# ---------------------------------------------------------------------------
# Backward-compatible re-exports from canonical source
# ---------------------------------------------------------------------------

THIN_BUILTIN_TOOLS: frozenset[str] = BUILTIN_TOOL_NAMES
THIN_BUILTIN_ALIASES: dict[str, str] = BUILTIN_ALIASES

# ---------------------------------------------------------------------------
# Mapping: thin builtin name → sandbox tool name
# ---------------------------------------------------------------------------

_THIN_TO_SANDBOX: dict[str, str] = {
    "read_file": "read",
    "write_file": "write",
    "edit_file": "edit",
    "execute": "bash",
    "ls": "ls",
    "glob": "glob",
    "grep": "grep",
}

# ---------------------------------------------------------------------------
# Schemas for tools without sandbox backing
# ---------------------------------------------------------------------------

_WRITE_TODOS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "todos": {"type": "string", "description": "Todo list content (markdown)"},
    },
    "required": ["todos"],
}

_TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "description": {"type": "string", "description": "Task description"},
    },
    "required": ["description"],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_thin_builtin_specs(
    sandbox: SandboxProvider | None = None,
    *,
    _sandbox_result: tuple[dict[str, ToolSpec], dict[str, Callable[..., Any]]] | None = None,
) -> list[ToolSpec]:
    """Create ToolSpec list for ThinRuntime built-in tools.

  Args:
    sandbox: SandboxProvider for file/exec tools. If None, returns empty list.
    _sandbox_result: Pre-computed create_sandbox_tools result (internal optimization).

  Returns:
    List of 9 ToolSpec objects with canonical Thin builtin names.
  """
    if sandbox is None:
        return []

    sandbox_specs: dict[str, ToolSpec]
    if _sandbox_result is not None:
        sandbox_specs = _sandbox_result[0]
    else:
        sandbox_specs, _ = create_sandbox_tools(sandbox)

    specs: list[ToolSpec] = []
    for thin_name, sandbox_name in _THIN_TO_SANDBOX.items():
        sandbox_spec = sandbox_specs.get(sandbox_name)
        if sandbox_spec is not None:
            specs.append(
                ToolSpec(
                    name=thin_name,
                    description=sandbox_spec.description,
                    parameters=sandbox_spec.parameters,
                    is_local=True,
                )
            )

    # write_todos -- stub tool (persists todo markdown)
    specs.append(
        ToolSpec(
            name="write_todos",
            description="Write or update todo list",
            parameters=_WRITE_TODOS_SCHEMA,
            is_local=True,
        )
    )

    # task -- stub tool (create/track task)
    specs.append(
        ToolSpec(
            name="task",
            description="Create or update a task",
            parameters=_TASK_SCHEMA,
            is_local=True,
        )
    )

    return specs


def get_thin_builtin_executors(
    sandbox: SandboxProvider,
    *,
    _sandbox_result: tuple[dict[str, ToolSpec], dict[str, Callable[..., Any]]] | None = None,
) -> dict[str, Callable[..., Any]]:
    """Create executor mapping for ThinRuntime built-in tools.

  Args:
    sandbox: SandboxProvider for file/exec tools.
    _sandbox_result: Pre-computed create_sandbox_tools result (internal optimization).

  Returns:
    Dict mapping canonical Thin name -> async callable executor.
  """
    sandbox_executors: dict[str, Callable[..., Any]]
    if _sandbox_result is not None:
        sandbox_executors = _sandbox_result[1]
    else:
        _, sandbox_executors = create_sandbox_tools(sandbox)

    executors: dict[str, Callable[..., Any]] = {}
    for thin_name, sandbox_name in _THIN_TO_SANDBOX.items():
        executor = sandbox_executors.get(sandbox_name)
        if executor is not None:
            executors[thin_name] = executor

    # write_todos -- simple file-based persistence
    async def _write_todos_executor(args: dict[str, Any]) -> str:
        todos = args.get("todos", "")
        try:
            await sandbox.write_file(".todos.md", todos)
            return json.dumps({"status": "ok", "path": ".todos.md"})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    executors["write_todos"] = _write_todos_executor

    # task -- simple noop (task tracking is handled at orchestration level)
    async def _task_executor(args: dict[str, Any]) -> str:
        description = args.get("description", "")
        return json.dumps({"status": "ok", "task": description, "note": "tracked"})

    executors["task"] = _task_executor

    return executors


def create_thin_builtin_tools(
    sandbox: SandboxProvider | None,
) -> tuple[dict[str, ToolSpec], dict[str, Callable[..., Any]]]:
    """Unified factory: create specs + executors for ThinRuntime built-in tools.

  Calls create_sandbox_tools once and passes the result to both
  get_Thin_builtin_specs and get_Thin_builtin_executors.

  Args:
    sandbox: SandboxProvider. If None, returns empty dicts.

  Returns:
    (specs_dict, executors_dict) with 9 tools.
  """
    if sandbox is None:
        return {}, {}

    sandbox_result = create_sandbox_tools(sandbox)

    spec_list = get_thin_builtin_specs(sandbox, _sandbox_result=sandbox_result)
    executors = get_thin_builtin_executors(sandbox, _sandbox_result=sandbox_result)

    specs_dict = {s.name: s for s in spec_list}
    return specs_dict, executors


def filter_thin_builtins_by_mode(
    specs: list[ToolSpec],
    feature_mode: str = "portable",
) -> list[ToolSpec]:
    """Filter built-in tool specs based on feature_mode.

  Args:
    specs: List of ToolSpec from get_Thin_builtin_specs().
    feature_mode: "portable" | "hybrid" | "native_first".

  Returns:
    Filtered list. Portable mode excludes all built-ins.
  """
    if feature_mode == "portable":
        return []
    return list(specs)


def merge_tools_with_builtins(
    user_tools: list[ToolSpec],
    builtin_tools: list[ToolSpec],
    feature_mode: str = "hybrid",
) -> list[ToolSpec]:
    """Merge tools with builtins."""
    if feature_mode == "portable":
        return list(user_tools)

    user_names = {t.name for t in user_tools}
    merged = list(user_tools)
    for bt in builtin_tools:
        if bt.name not in user_names:
            merged.append(bt)
    return merged
