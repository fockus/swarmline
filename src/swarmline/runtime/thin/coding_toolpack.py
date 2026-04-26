"""CodingToolPack — canonical coding tool surface built from shared builtins.

Single builder that produces both ToolSpecs and executors for the
coding profile. The visible tool surface == executable tool surface
(CADG-02: name parity from one builder).

Phase 8 expansion: CODING_TOOL_NAMES includes todo_read/todo_write.
build_coding_toolpack optionally wires todo tools when a TodoProvider is given.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from swarmline.runtime.types import ToolSpec

# Canonical tool name sets — used by policy and builder.
CODING_SANDBOX_TOOL_NAMES: frozenset[str] = frozenset(
    {"read", "write", "edit", "multi_edit", "bash", "ls", "glob", "grep"}
)

CODING_TODO_TOOL_NAMES: frozenset[str] = frozenset({"todo_read", "todo_write"})

# Full canonical coding tool surface (sandbox + todo).
CODING_TOOL_NAMES: frozenset[str] = CODING_SANDBOX_TOOL_NAMES | CODING_TODO_TOOL_NAMES


# ---------------------------------------------------------------------------
# COMP-01: Legacy alias → canonical coding tool mapping
# ---------------------------------------------------------------------------

CODING_ALIAS_MAP: dict[str, str] = {
    "read_file": "read",
    "write_file": "write",
    "edit_file": "edit",
    "execute": "bash",
    "write_todos": "todo_write",
}


def resolve_coding_alias(name: str | None) -> str:
    """Resolve a tool name: alias → canonical, canonical → passthrough.

    Args:
        name: Tool name to resolve. May be a legacy alias or canonical name.

    Returns:
        Canonical tool name.

    Raises:
        ValueError: If name is None, empty, or not a known alias/canonical.
        TypeError: If name is not a string.
    """
    if name is None:
        raise TypeError("Tool name must be a string, got None")
    if not isinstance(name, str):
        raise TypeError(f"Tool name must be a string, got {type(name).__name__}")
    if not name.strip():
        raise ValueError("Tool name must not be empty")

    # Direct alias hit
    if name in CODING_ALIAS_MAP:
        return CODING_ALIAS_MAP[name]

    # Canonical name passthrough (includes alias targets for forward-compat)
    all_canonical = CODING_TOOL_NAMES | set(CODING_ALIAS_MAP.values())
    if name in all_canonical:
        return name

    raise ValueError(
        f"Unsupported alias or unknown tool: '{name}'. "
        f"Known aliases: {sorted(CODING_ALIAS_MAP.keys())}. "
        f"Known canonical: {sorted(CODING_TOOL_NAMES)}"
    )


def build_alias_specs(pack: CodingToolPack) -> dict[str, ToolSpec]:
    """Build ToolSpec objects for legacy alias names that delegate to canonical.

    Each alias spec has the same description and parameters as the canonical
    tool it maps to, ensuring COMP-03 (no second implementation path).

    Only produces aliases whose canonical target exists in the pack.

    Args:
        pack: CodingToolPack with canonical specs.

    Returns:
        Dict mapping alias name → ToolSpec (alias name, canonical description).
    """
    alias_specs: dict[str, ToolSpec] = {}
    for alias_name, canonical_name in CODING_ALIAS_MAP.items():
        if canonical_name in pack.specs:
            canonical_spec = pack.specs[canonical_name]
            alias_specs[alias_name] = ToolSpec(
                name=alias_name,
                description=canonical_spec.description,
                parameters=canonical_spec.parameters,
                is_local=True,
            )
    return alias_specs


def _freeze_mapping(d: dict[str, Any]) -> Mapping[str, Any]:
    """Wrap a dict as a read-only MappingProxy."""
    return MappingProxyType(d)


@dataclass(frozen=True)
class CodingToolPack:
    """Bundle of specs + executors with name parity guarantee.

    Invariant: set(specs.keys()) == set(executors.keys())
    specs and executors are read-only after construction.
    """

    specs: Mapping[str, ToolSpec] = field(default_factory=dict)
    executors: Mapping[str, Callable[..., Any]] = field(default_factory=dict)

    @property
    def tool_names(self) -> frozenset[str]:
        """Return the canonical tool name set."""
        return frozenset(self.specs.keys())


def build_coding_toolpack(
    sandbox: Any,
    *,
    todo_provider: Any = None,
) -> CodingToolPack:
    """Build the canonical coding tool pack from a SandboxProvider.

    Uses create_sandbox_tools() as the single source of truth for
    sandbox specs and executors (CADG-03).

    When todo_provider is given, also includes todo_read/todo_write from
    create_todo_tools() (CTSK-02).

    Args:
        sandbox: SandboxProvider for file/shell tools. Required.
        todo_provider: Optional TodoProvider for todo_read/todo_write.

    Raises:
        ValueError: If sandbox is None.
        RuntimeError: If built tool set doesn't match expected names.
    """
    if sandbox is None:
        raise ValueError("sandbox is required for coding tool pack")

    from swarmline.tools.builtin import create_sandbox_tools

    raw_specs, raw_executors = create_sandbox_tools(sandbox)

    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable[..., Any]] = {}

    # Sandbox tools (always built)
    for name in CODING_SANDBOX_TOOL_NAMES:
        if name not in raw_specs:
            raise RuntimeError(
                f"Coding tool '{name}' not found in create_sandbox_tools output. "
                f"Available: {sorted(raw_specs.keys())}"
            )
        specs[name] = raw_specs[name]
        executors[name] = raw_executors[name]

    # Todo tools (when provider is given)
    if todo_provider is not None:
        from swarmline.todo.tools import create_todo_tools

        todo_specs, todo_executors = create_todo_tools(todo_provider)
        for name in CODING_TODO_TOOL_NAMES:
            if name not in todo_specs:
                raise RuntimeError(
                    f"Todo tool '{name}' not found in create_todo_tools output. "
                    f"Available: {sorted(todo_specs.keys())}"
                )
            specs[name] = todo_specs[name]
            executors[name] = todo_executors[name]

    return CodingToolPack(
        specs=_freeze_mapping(specs),
        executors=_freeze_mapping(executors),
    )
