"""Policy helpers for native built-ins DeepAgents."""

from __future__ import annotations

from dataclasses import dataclass

from swarmline.runtime.builtin_names import BUILTIN_ALIASES, BUILTIN_TOOL_NAMES
from swarmline.runtime.types import ToolSpec

# Backward-compatible re-exports from canonical source
DEEPAGENTS_NATIVE_BUILTIN_TOOLS: frozenset[str] = BUILTIN_TOOL_NAMES
DEEPAGENTS_NATIVE_BUILTIN_ALIASES: dict[str, str] = BUILTIN_ALIASES


@dataclass(frozen=True)
class DeepAgentsBuiltinSelection:
    """Deep Agents Builtin Selection implementation."""

    custom_tools: list[ToolSpec]
    native_tool_names: list[str]
    alias_mappings: list[tuple[str, str]]


def canonicalize_builtin_name(name: str) -> str | None:
    """Return canonical native built-in name or None."""
    if name in DEEPAGENTS_NATIVE_BUILTIN_TOOLS:
        return name
    return DEEPAGENTS_NATIVE_BUILTIN_ALIASES.get(name)


def split_native_builtin_tools(
    tools: list[ToolSpec],
) -> DeepAgentsBuiltinSelection:
    """Split native builtin tools."""
    custom_tools: list[ToolSpec] = []
    native_tool_names: list[str] = []
    alias_mappings: list[tuple[str, str]] = []
    seen_native: set[str] = set()
    seen_aliases: set[tuple[str, str]] = set()

    for tool in tools:
        canonical_name = canonicalize_builtin_name(tool.name)
        if canonical_name is None:
            custom_tools.append(tool)
            continue

        if canonical_name not in seen_native:
            seen_native.add(canonical_name)
            native_tool_names.append(canonical_name)

        if tool.name != canonical_name:
            mapping = (tool.name, canonical_name)
            if mapping not in seen_aliases:
                seen_aliases.add(mapping)
                alias_mappings.append(mapping)

    return DeepAgentsBuiltinSelection(
        custom_tools=custom_tools,
        native_tool_names=native_tool_names,
        alias_mappings=alias_mappings,
    )


def filter_native_builtin_tools(tools: list[ToolSpec]) -> list[ToolSpec]:
    """Filter native builtin tools."""
    return split_native_builtin_tools(tools).custom_tools


def build_portable_notice(tools: list[ToolSpec]) -> str | None:
    """Build portable notice."""
    selection = split_native_builtin_tools(tools)
    if not selection.native_tool_names:
        return None

    native_list = ", ".join(selection.native_tool_names)
    return f"DeepAgents portable mode пропускает native built-ins: {native_list}"


def build_native_notice(
    tools: list[ToolSpec],
    *,
    feature_mode: str,
) -> str | None:
    """Build status notice for native/hybrid path."""
    selection = split_native_builtin_tools(tools)
    if not selection.native_tool_names:
        return None

    prefix = "DeepAgents native built-ins active"
    if feature_mode == "native_first":
        prefix = "DeepAgents native-first mode preferring built-ins"

    parts = [prefix]
    if selection.alias_mappings:
        mapped = ", ".join(f"{source}->{target}" for source, target in selection.alias_mappings)
        parts.append(f"mapped aliases: {mapped}")
    parts.append(f"native tools: {', '.join(selection.native_tool_names)}")
    return "; ".join(parts)
