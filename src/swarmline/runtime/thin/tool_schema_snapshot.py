"""Tool-schema snapshot — AGR-004: tool schemas resolve ONCE per run.

Stage 3 (context-engineering-manus-parity): a run's tool-call schema list must
stay byte-identical across every turn/call sharing the same ``run_id`` (Manus
canon — KV cache hit-rate depends on the tools payload never "breathing"
mid-run, exactly like the system-prompt static prefix from Stage 1/2).

This module is the pure, deterministic-sort/serialize half of that contract.
The react loop (``runtime/thin/react_strategy.py``) is the only caller: it
persists/reloads the snapshot through the EXISTING OSS-T4 checkpoint substrate
(``CheckpointWriter``, keyed by ``run_id``) — no new persistence mechanism, no
taskloom coupling, no state-machine on top of it (YAGNI).
"""

from __future__ import annotations

from typing import Any, cast

from swarmline.domain_types import ToolSpec

#: Reserved checkpoint state key for the pinned tool-schema snapshot — mirrors
#: the CHECKPOINT_KEY_STEP/_TOTAL reserved-key convention in resilience/checkpoint.py.
CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT = "_tool_schema_snapshot"


def canonicalize_tools(tools: list[ToolSpec]) -> list[ToolSpec]:
    """Deterministically sort tools by name.

    Applied once, before the first LLM call of a run — the returned order (and
    therefore the serialized tools payload) never depends on discovery/merge
    order (MCP servers, capability broker, ...), only on tool name.
    """
    return sorted(tools, key=lambda t: t.name)


def snapshot_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    """Serialize a canonicalized tool list into a JSON-safe snapshot."""
    return [t.to_dict() for t in canonicalize_tools(tools)]


def _is_valid_snapshot_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    # ty narrows `isinstance(entry, dict)` to an untyped dict (key/value types
    # cannot be recovered from a runtime isinstance check); cast to the
    # declared shape before calling .get(), matching the established pattern
    # elsewhere in this codebase (e.g. context/prompt_caching.py's block cast).
    candidate = cast("dict[str, Any]", entry)
    return (
        isinstance(candidate.get("name"), str)
        and isinstance(candidate.get("description"), str)
        and isinstance(candidate.get("parameters"), dict)
    )


def restore_tools(snapshot: list[Any]) -> list[ToolSpec] | None:
    """Reconstruct ``ToolSpec`` objects from a snapshot produced by ``snapshot_tools()``.

    Returns ``None`` (fail-safe) if any entry is malformed — a third-party
    ``CheckpointPort`` could return corrupted/foreign state; rejecting it here
    means the caller falls back to resolving a FRESH snapshot instead of
    crashing downstream on a ``KeyError``/``TypeError``.
    """
    if not all(_is_valid_snapshot_entry(entry) for entry in snapshot):
        return None
    return [
        ToolSpec(
            name=entry["name"],
            description=entry["description"],
            parameters=entry["parameters"],
            is_local=bool(entry.get("is_local", False)),
        )
        for entry in snapshot
    ]


def resolve_pinned_tools(
    tools: list[ToolSpec],
    checkpoint_state: dict[str, object] | None,
) -> tuple[list[ToolSpec], list[dict[str, Any]]]:
    """Resolve the EFFECTIVE tool list for this call of the run.

    - ``checkpoint_state`` carries a valid snapshot (a later turn, or a resume,
      of the SAME ``run_id``): that snapshot is reused VERBATIM — the freshly
      passed ``tools`` argument's order/content is ignored entirely, pinning
      the schema exactly as it was on first resolution.
    - Otherwise (first call for this run, or no valid snapshot to reuse):
      ``tools`` is canonicalized (deterministic sort) and a NEW snapshot is
      minted for the caller to persist going forward.

    Returns ``(effective_tools, snapshot_to_persist)`` — the second element is
    always JSON-safe and always reflects exactly what ``effective_tools``
    contains, so persisting it is a no-op when reused.
    """
    if checkpoint_state is not None:
        saved = checkpoint_state.get(CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT)
        if isinstance(saved, list):
            restored = restore_tools(saved)
            if restored is not None:
                # restore_tools() already validated every element's shape (name/
                # description/parameters); the cast reflects that proof to ty,
                # which cannot recover element types from the isinstance(list) check.
                return restored, cast("list[dict[str, Any]]", saved)

    canonical = canonicalize_tools(tools)
    return canonical, [t.to_dict() for t in canonical]


__all__ = [
    "CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT",
    "canonicalize_tools",
    "resolve_pinned_tools",
    "restore_tools",
    "snapshot_tools",
]
