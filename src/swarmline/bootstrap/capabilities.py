"""Capabilities wiring - assemble tools from independent capabilities.

Six capabilities with separate toggles:
sandbox, web, todo, memory_bank, planning, thinking.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from swarmline.policy.tool_selector import ToolBudgetConfig, ToolGroup, ToolSelector
from swarmline.runtime.types import ToolSpec


def collect_capability_tools(
    *,
    sandbox_provider: Any | None = None,
    web_provider: Any | None = None,
    todo_provider: Any | None = None,
    memory_bank_provider: Any | None = None,
    plan_manager: Any | None = None,
    plan_user_id: str = "",
    plan_topic_id: str = "",
    thinking_enabled: bool = True,
    tool_budget_config: ToolBudgetConfig | None = None,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Assemble tools from all enabled capabilities.

    Args:
        sandbox_provider: SandboxProvider -> bash, read, write, edit, ...
        web_provider: WebProvider -> web_fetch, web_search.
        todo_provider: TodoProvider -> todo_read, todo_write.
        memory_bank_provider: MemoryBankProvider -> memory_read, memory_write, ...
        plan_manager: PlanManager -> plan_create, plan_status, plan_execute.
        plan_user_id: user_id for the plan namespace.
        plan_topic_id: topic_id for the plan namespace.
        thinking_enabled: -> thinking tool (standalone).
        tool_budget_config: Tool selection budget (optional).

    Returns:
        Tuple: (merged specs, merged executors).
    """
    all_specs: dict[str, ToolSpec] = {}
    all_executors: dict[str, Callable] = {}

    # Sandbox tools
    if sandbox_provider is not None:
        from swarmline.tools.builtin import create_sandbox_tools

        specs, executors = create_sandbox_tools(sandbox_provider)
        all_specs.update(specs)
        all_executors.update(executors)

    # Web tools
    if web_provider is not None:
        from swarmline.tools.builtin import create_web_tools

        specs, executors = create_web_tools(web_provider)
        all_specs.update(specs)
        all_executors.update(executors)

    # Todo tools
    if todo_provider is not None:
        from swarmline.todo.tools import create_todo_tools

        specs, executors = create_todo_tools(todo_provider)
        all_specs.update(specs)
        all_executors.update(executors)

    # Plan tools
    if plan_manager is not None:
        from swarmline.orchestration.plan_tools import create_plan_tools

        specs, executors = create_plan_tools(plan_manager, plan_user_id, plan_topic_id)
        all_specs.update(specs)
        all_executors.update(executors)

    # Memory Bank tools
    if memory_bank_provider is not None:
        from swarmline.memory_bank.tools import create_memory_bank_tools

        specs, executors = create_memory_bank_tools(memory_bank_provider)
        all_specs.update(specs)
        all_executors.update(executors)

    # Thinking tool (standalone)
    if thinking_enabled:
        from swarmline.tools.thinking import create_thinking_tool

        spec, executor = create_thinking_tool()
        all_specs[spec.name] = spec
        all_executors[spec.name] = executor

    if tool_budget_config is not None:
        selected_names = _select_tool_names_by_budget(all_specs, tool_budget_config)
        all_specs = {name: spec for name, spec in all_specs.items() if name in selected_names}
        all_executors = {
            name: executor for name, executor in all_executors.items() if name in selected_names
        }

    return all_specs, all_executors


def _select_tool_names_by_budget(
    specs: dict[str, ToolSpec],
    config: ToolBudgetConfig,
) -> set[str]:
    selector = ToolSelector(config=config)
    grouped: dict[ToolGroup, list[ToolSpec]] = {}
    for spec in specs.values():
        group = _tool_group_for_name(spec.name)
        grouped.setdefault(group, []).append(spec)

    for group, tools in grouped.items():
        selector.add_group(group, tools)

    return {tool.name for tool in selector.select()}


def _tool_group_for_name(tool_name: str) -> ToolGroup:
    if tool_name == "thinking" or tool_name.startswith("todo_"):
        return ToolGroup.ALWAYS
    if tool_name.startswith("memory_"):
        return ToolGroup.MEMORY
    if tool_name.startswith("plan_"):
        return ToolGroup.PLANNING
    if tool_name in {"bash", "read", "write", "edit", "multi_edit", "ls", "glob", "grep"}:
        return ToolGroup.SANDBOX
    if tool_name.startswith("web_"):
        return ToolGroup.WEB
    return ToolGroup.MCP
