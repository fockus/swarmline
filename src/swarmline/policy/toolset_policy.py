"""ToolsetPolicy — spawn-time role→toolset allowlist for LLM-initiated subagents.

Closes the security seam at `runtime/thin/subagent_tool.py::create_subagent_executor`
where a `spawn_agent` call with no `tools=` argument inherited the parent's FULL
toolset (`child_tools = list(parent_tools)`). REQ-ORC-040/041/042:

- REQ-ORC-040: a spawned subagent is granted only the tools named by an
  explicit `ToolsetPolicy` for its role, not the parent's full toolset.
- REQ-ORC-041: when a spawn request names no scoped toolset, the system
  default-denies inheritance of the parent's full toolset rather than
  granting it.
- REQ-ORC-042: a `researcher` subagent is scoped to research/discovery
  tools (codebase, web, skill/registry lookup) only.

This is a SPAWN-TIME role→names map — a different layer from
`policy/tool_policy.py::DefaultToolPolicy`, which is a per-call
`can_use_tool` gate applied while an agent is running. The two are not
merged; `ALWAYS_DENIED_TOOLS` is not reused here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

# Research/discovery tools per REQ-ORC-042: codebase lookup (read/grep/glob/ls),
# web lookup (web_search/web_fetch), and skill/registry lookup (read_skill).
# Canonical builtin snake_case tool names.
RESEARCHER_TOOLS: frozenset[str] = frozenset(
    {
        "read",
        "grep",
        "glob",
        "ls",
        "web_search",
        "web_fetch",
        "read_skill",
    }
)


@dataclass(frozen=True)
class ToolsetPolicy:
    """Role → allowed tool names, for gating LLM-initiated subagent spawns.

    An unknown role resolves to an EMPTY frozenset (default-deny, REQ-ORC-041):
    a spawn request for a role with no explicit policy entry gets no tools
    rather than falling back to the parent's full toolset.
    """

    roles: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def allowed_tools(self, role: str) -> frozenset[str]:
        """Return the allowed tool names for `role` (empty = default-deny)."""
        return self.roles.get(role, frozenset())

    @classmethod
    def researcher(cls) -> ToolsetPolicy:
        """Policy with a single `researcher` role scoped to research tools."""
        return cls(roles={"researcher": RESEARCHER_TOOLS})


def default_toolset_policy() -> ToolsetPolicy:
    """Module-level factory mirroring `ToolsetPolicy.researcher()`."""
    return ToolsetPolicy.researcher()
