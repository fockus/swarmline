"""CodingToolPack — canonical coding tool surface built from shared builtins.

Single builder that produces both ToolSpecs and executors for the
coding profile. The visible tool surface == executable tool surface
(CADG-02: name parity from one builder).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from swarmline.runtime.types import ToolSpec

# Canonical coding tool names — the ONLY names exposed and allowed.
CODING_TOOL_NAMES: frozenset[str] = frozenset(
    {"read", "write", "edit", "multi_edit", "bash", "ls", "glob", "grep"}
)


def _freeze_mapping(d: dict[str, Any]) -> Mapping[str, Any]:
    """Wrap a dict as a read-only MappingProxy."""
    return MappingProxyType(d)


@dataclass(frozen=True)
class CodingToolPack:
    """Bundle of specs + executors with name parity guarantee.

    Invariant: set(specs.keys()) == set(executors.keys()) == CODING_TOOL_NAMES
    specs and executors are read-only after construction.
    """

    specs: Mapping[str, ToolSpec] = field(default_factory=dict)
    executors: Mapping[str, Callable[..., Any]] = field(default_factory=dict)

    @property
    def tool_names(self) -> frozenset[str]:
        """Return the canonical tool name set."""
        return frozenset(self.specs.keys())


def build_coding_toolpack(sandbox: Any) -> CodingToolPack:
    """Build the canonical coding tool pack from a SandboxProvider.

    Uses create_sandbox_tools() as the single source of truth for
    both specs and executors (CADG-03).

    Raises:
        ValueError: If sandbox is None.
        RuntimeError: If built tool set doesn't match CODING_TOOL_NAMES.
    """
    if sandbox is None:
        raise ValueError("sandbox is required for coding tool pack")

    from swarmline.tools.builtin import create_sandbox_tools

    raw_specs, raw_executors = create_sandbox_tools(sandbox)

    # Filter to only canonical coding tool names
    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable[..., Any]] = {}

    for name in CODING_TOOL_NAMES:
        if name not in raw_specs:
            raise RuntimeError(
                f"Coding tool '{name}' not found in create_sandbox_tools output. "
                f"Available: {sorted(raw_specs.keys())}"
            )
        specs[name] = raw_specs[name]
        executors[name] = raw_executors[name]

    built_names = frozenset(specs.keys())
    if built_names != CODING_TOOL_NAMES:  # pragma: no cover — defense-in-depth after loop
        raise RuntimeError(
            f"Tool set drift: built={sorted(built_names)}, "
            f"expected={sorted(CODING_TOOL_NAMES)}"
        )

    return CodingToolPack(
        specs=_freeze_mapping(specs),
        executors=_freeze_mapping(executors),
    )
