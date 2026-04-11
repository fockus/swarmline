"""Tests policy/mapping layer for built-ins DeepAgents."""

from __future__ import annotations

from swarmline.runtime.types import ToolSpec


def test_builtin_tool_names_match_upstream_contract() -> None:
    """Canonical built-ins are the same as upstream create_deep_agent()."""
    from swarmline.runtime.deepagents_builtins import DEEPAGENTS_NATIVE_BUILTIN_TOOLS

    assert {
        "write_todos",
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "execute",
        "task",
    } == DEEPAGENTS_NATIVE_BUILTIN_TOOLS


def test_canonicalize_builtin_name_maps_claude_style_aliases() -> None:
    """Claude-style alias names are mapped in canonical DeepAgents built-ins."""
    from swarmline.runtime.deepagents_builtins import canonicalize_builtin_name

    assert canonicalize_builtin_name("Bash") == "execute"
    assert canonicalize_builtin_name("Task") == "task"
    assert canonicalize_builtin_name("TodoWrite") == "write_todos"
    assert canonicalize_builtin_name("Read") == "read_file"
    assert canonicalize_builtin_name("calc") is None


def test_filter_native_builtin_tools_removes_aliases_and_canonical_names() -> None:
    """Portable filter cuts out both aliases and canonical native built-ins."""
    from swarmline.runtime.deepagents_builtins import filter_native_builtin_tools

    tools = [
        ToolSpec(name="Bash", description="shell", parameters={}),
        ToolSpec(name="execute", description="shell", parameters={}),
        ToolSpec(name="read_file", description="read", parameters={}),
        ToolSpec(name="calc", description="calculator", parameters={}, is_local=True),
    ]

    filtered = filter_native_builtin_tools(tools)

    assert [tool.name for tool in filtered] == ["calc"]


def test_split_native_builtin_tools_returns_custom_tools_and_mappings() -> None:
    """Native path separates built-ins from custom tools and dedupe and canonical names."""
    from swarmline.runtime.deepagents_builtins import split_native_builtin_tools

    tools = [
        ToolSpec(name="Bash", description="shell", parameters={}),
        ToolSpec(name="task", description="subagent", parameters={}),
        ToolSpec(name="calc", description="calculator", parameters={}, is_local=True),
        ToolSpec(name="TodoWrite", description="todo", parameters={}),
        ToolSpec(name="execute", description="shell", parameters={}),
    ]

    selection = split_native_builtin_tools(tools)

    assert selection.native_tool_names == ["execute", "task", "write_todos"]
    assert selection.alias_mappings == [
        ("Bash", "execute"),
        ("TodoWrite", "write_todos"),
    ]
    assert [tool.name for tool in selection.custom_tools] == ["calc"]
