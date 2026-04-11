"""Canonical built-in tool names and aliases - single source of truth.

Used by both ThinRuntime and DeepAgents runtime for built-in tool
identification, alias resolution, and portable/native mode filtering.
"""

from __future__ import annotations

BUILTIN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "ls",
        "glob",
        "grep",
        "execute",
        "write_todos",
        "task",
    }
)

BUILTIN_ALIASES: dict[str, str] = {
    "TodoRead": "write_todos",
    "TodoWrite": "write_todos",
    "LS": "ls",
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "edit_file",
    "MultiEdit": "edit_file",
    "Glob": "glob",
    "Grep": "grep",
    "Bash": "execute",
    "Task": "task",
}
