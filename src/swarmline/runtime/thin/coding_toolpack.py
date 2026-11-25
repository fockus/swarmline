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
from typing import TYPE_CHECKING, Any

from swarmline.runtime.types import ToolSpec

if TYPE_CHECKING:
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig

# Canonical tool name sets — used by policy and builder.
CODING_SANDBOX_TOOL_NAMES: frozenset[str] = frozenset(
    {"read", "write", "edit", "multi_edit", "bash", "ls", "glob", "grep"}
)

CODING_TODO_TOOL_NAMES: frozenset[str] = frozenset({"todo_read", "todo_write"})

# Opt-in code-intelligence tools (Task 3). Wired into the pack ONLY when
# config.enable_repo_map_ranking is True. NOT part of the canonical default
# CODING_TOOL_NAMES surface (which stays the 8 sandbox + 2 todo set); when wired,
# runtime_wiring expands the policy allowlist with these names so they are callable.
CODING_CODE_INTEL_TOOL_NAMES: frozenset[str] = frozenset(
    {"repo_map", "impact_analysis", "find_seams", "plan_edit", "check_coverage"}
)

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
    config: CodingProfileConfig | None = None,
    todo_provider: Any = None,
) -> CodingToolPack:
    """Build the canonical coding tool pack from a SandboxProvider.

    Uses create_sandbox_tools() as the single source of truth for
    sandbox specs and executors (CADG-03).

    When todo_provider is given, also includes todo_read/todo_write from
    create_todo_tools() (CTSK-02).

    When config is None or all flags are at their defaults (off/legacy), the
    output is byte-identical to the no-config call — no new tools or hooks are
    registered (B2 propagation seam for Task 1+).

    Args:
        sandbox: SandboxProvider for file/shell tools. Required.
        config: Optional CodingProfileConfig. When None, legacy behaviour is
                preserved. Passed through to create_sandbox_tools for future
                flag-gated features (Tasks 1-8).
        todo_provider: Optional TodoProvider for todo_read/todo_write.

    Raises:
        ValueError: If sandbox is None.
        RuntimeError: If built tool set doesn't match expected names.
    """
    if sandbox is None:
        raise ValueError("sandbox is required for coding tool pack")

    from swarmline.tools.builtin import create_sandbox_tools

    raw_specs, raw_executors = create_sandbox_tools(sandbox, config=config)

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

    # Opt-in transactional multi-file edit tool (Task 1). create_sandbox_tools
    # only emits "multi_file_edit" when config.edit_strategy != "legacy", so the
    # legacy/None path never registers it (regression-guarded by Task 0 tests).
    if config is not None and config.edit_strategy != "legacy":
        if "multi_file_edit" in raw_specs:
            specs["multi_file_edit"] = raw_specs["multi_file_edit"]
            executors["multi_file_edit"] = raw_executors["multi_file_edit"]

    # Opt-in code-intelligence tools (Task 3). Mirrors the multi_file_edit opt-in:
    # only included when ranking is explicitly enabled, so the legacy/None path is
    # byte-identical (no code_intel tools, no rank key anywhere).
    if config is not None and config.enable_repo_map_ranking:
        ci_specs, ci_executors = _build_code_intel_pack(config)
        for name in CODING_CODE_INTEL_TOOL_NAMES:
            specs[name] = ci_specs[name]
            executors[name] = ci_executors[name]

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


def _build_code_intel_pack(
    config: CodingProfileConfig,
) -> tuple[dict[str, ToolSpec], dict[str, Callable[..., Any]]]:
    """Build the 5 code-intel tools with a ranked, budgeted ``repo_map``.

    Wires the default analyzers (ASTRepoMapper, GraphImpactAnalyzer, Python/TS
    seam parsers, ImportBasedCoverageAnalyzer) into ``create_code_intel_tools``;
    the other 4 tools use those defaults verbatim. The ``repo_map`` executor is
    REPLACED with a ranked+budgeted serialization driven by ``RankedRepoMapper``
    so its output carries per-symbol ``rank`` (sorted descending, truncated to
    ``config.repo_map_max_tokens`` via ``RepoMapBudget``).
    """
    from swarmline.code_intel.coverage_checker import ImportBasedCoverageAnalyzer
    from swarmline.code_intel.impact_analyzer import GraphImpactAnalyzer
    from swarmline.code_intel.language_parsers import (
        CompositeLanguageParser,
        PythonSeamParser,
        TypeScriptSeamParser,
    )
    from swarmline.code_intel.ranked_repo_mapper import (
        RankedRepoMapper,
        RepoMapBudget,
    )
    from swarmline.code_intel.repo_mapper import ASTRepoMapper
    from swarmline.code_intel.tools import create_code_intel_tools, serialize_repo_map

    base_mapper = ASTRepoMapper()
    language_parser = CompositeLanguageParser()
    language_parser.register_parser(PythonSeamParser())
    language_parser.register_parser(TypeScriptSeamParser())

    ci_specs, ci_executors = create_code_intel_tools(
        repo_mapper=base_mapper,
        impact_analyzer=GraphImpactAnalyzer(),
        language_parser=language_parser,
        coverage_analyzer=ImportBasedCoverageAnalyzer(),
    )

    ranked_mapper = RankedRepoMapper(base=base_mapper)
    budget = RepoMapBudget(max_tokens=config.repo_map_max_tokens)

    def _ranked_repo_map(args: dict[str, Any]) -> str:
        from swarmline.code_intel.tools import _error_json

        from swarmline.code_intel.ranked_repo_mapper import RankedSymbol

        root_path = args.get("root_path", "")
        if not root_path:
            return _error_json("validation", "root_path is required")
        extensions = set(args.get("extensions", [".py"]))
        repo_map = ranked_mapper.scan_repo(root_path, extensions)
        ranked = ranked_mapper.rank(repo_map)

        # F3: bound the FULL serialized output (root_path + files + imports + symbols),
        # not just the symbols list — the ~4-chars-per-token heuristic over the exact
        # JSON the tool will emit. fit() returns () if the fixed overhead alone blows
        # the budget (unavoidable structural minimum).
        def _measure_full(prefix: tuple[RankedSymbol, ...]) -> int:
            return len(serialize_repo_map(repo_map, ranking=prefix)) // 4

        fitted = budget.fit(ranked, measure=_measure_full)
        return serialize_repo_map(repo_map, ranking=fitted)

    ci_executors["repo_map"] = _ranked_repo_map
    return ci_specs, ci_executors
