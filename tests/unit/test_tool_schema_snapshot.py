"""Tests for swarmline.runtime.thin.tool_schema_snapshot — Stage 3 (AGR-004).

TDD file: written BEFORE wiring into react_strategy.py. Covers the pure
canonicalize/snapshot/restore/resolve_pinned_tools functions in isolation.
"""

from __future__ import annotations

from swarmline.runtime.thin.tool_schema_snapshot import (
    CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT,
    canonicalize_tools,
    resolve_pinned_tools,
    restore_tools,
    snapshot_tools,
)
from swarmline.runtime.types import ToolSpec

_TOOL_A = ToolSpec(
    name="alpha", description="a tool", parameters={"type": "object", "properties": {}}
)
_TOOL_B = ToolSpec(
    name="beta", description="b tool", parameters={"type": "object", "properties": {}}
)
_TOOL_C = ToolSpec(
    name="gamma", description="c tool", parameters={"type": "object", "properties": {}}
)


class TestCanonicalizeTools:
    def test_sorts_by_name_regardless_of_input_order(self) -> None:
        result = canonicalize_tools([_TOOL_C, _TOOL_A, _TOOL_B])
        assert [t.name for t in result] == ["alpha", "beta", "gamma"]

    def test_empty_list_returns_empty_list(self) -> None:
        assert canonicalize_tools([]) == []

    def test_does_not_mutate_input_list(self) -> None:
        original = [_TOOL_C, _TOOL_A]
        canonicalize_tools(original)
        assert original == [_TOOL_C, _TOOL_A]


class TestSnapshotTools:
    def test_snapshot_is_sorted_and_json_safe(self) -> None:
        snapshot = snapshot_tools([_TOOL_B, _TOOL_A])
        assert snapshot == [
            {
                "name": "alpha",
                "description": "a tool",
                "parameters": {"type": "object", "properties": {}},
                "is_local": False,
            },
            {
                "name": "beta",
                "description": "b tool",
                "parameters": {"type": "object", "properties": {}},
                "is_local": False,
            },
        ]


class TestRestoreTools:
    def test_round_trips_through_snapshot(self) -> None:
        snapshot = snapshot_tools([_TOOL_A, _TOOL_B])
        restored = restore_tools(snapshot)
        assert restored == [_TOOL_A, _TOOL_B]

    def test_malformed_entry_returns_none(self) -> None:
        assert restore_tools([{"name": "x"}]) is None  # missing description/parameters

    def test_non_dict_entry_returns_none(self) -> None:
        assert restore_tools(["not-a-dict"]) is None

    def test_empty_snapshot_restores_to_empty_list(self) -> None:
        assert restore_tools([]) == []


class TestResolvePinnedTools:
    def test_no_checkpoint_state_canonicalizes_and_mints_snapshot(self) -> None:
        effective, snapshot = resolve_pinned_tools([_TOOL_C, _TOOL_A], None)

        assert [t.name for t in effective] == ["alpha", "gamma"]
        assert snapshot == snapshot_tools([_TOOL_A, _TOOL_C])

    def test_checkpoint_with_no_snapshot_key_canonicalizes_fresh(self) -> None:
        effective, snapshot = resolve_pinned_tools(
            [_TOOL_B, _TOOL_A], {"iterations": 1}
        )

        assert [t.name for t in effective] == ["alpha", "beta"]

    def test_checkpoint_with_valid_snapshot_reuses_it_verbatim_ignoring_fresh_tools(
        self,
    ) -> None:
        """The key invariant: a DIFFERENT (even larger/smaller) fresh tool list
        passed on a later turn must NOT change the effective/pinned schema."""
        prior_snapshot = snapshot_tools([_TOOL_A, _TOOL_B])
        checkpoint_state = {CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT: prior_snapshot}

        effective, snapshot = resolve_pinned_tools(
            [_TOOL_C, _TOOL_A, _TOOL_B],  # a "later turn" discovered an extra tool
            checkpoint_state,
        )

        assert [t.name for t in effective] == ["alpha", "beta"]  # gamma NOT included
        assert snapshot == prior_snapshot

    def test_checkpoint_with_corrupted_snapshot_falls_back_to_fresh_canonicalization(
        self,
    ) -> None:
        checkpoint_state = {
            CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT: [{"name": "only-a-name"}]
        }

        effective, _snapshot = resolve_pinned_tools(
            [_TOOL_B, _TOOL_A], checkpoint_state
        )

        assert [t.name for t in effective] == ["alpha", "beta"]

    def test_persisted_snapshot_round_trips_stably_across_repeated_resolutions(
        self,
    ) -> None:
        """Simulates N turns: resolve once, persist, resolve again from the
        persisted state -> must reproduce byte-identical effective tools/snapshot."""
        _first_effective, first_snapshot = resolve_pinned_tools(
            [_TOOL_B, _TOOL_A], None
        )
        second_effective, second_snapshot = resolve_pinned_tools(
            [_TOOL_A],  # a DIFFERENT (narrower) fresh set on turn 2
            {CHECKPOINT_KEY_TOOL_SCHEMA_SNAPSHOT: first_snapshot},
        )

        assert second_snapshot == first_snapshot
        assert [t.name for t in second_effective] == ["alpha", "beta"]
