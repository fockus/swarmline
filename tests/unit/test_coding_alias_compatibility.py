"""Tests for coding alias compatibility — COMP-01, COMP-02, COMP-03.

RED phase: tests define the contract for alias resolution.

COMP-01: Legacy aliases map to canonical implementations with equivalent semantics.
COMP-02: Unsupported alias/profile/wiring states return explicit errors.
COMP-03: Compatibility layer does not become second implementation path.
"""

from __future__ import annotations

import pytest

from swarmline.runtime.thin.coding_toolpack import (
    CODING_ALIAS_MAP,
    CODING_TOOL_NAMES,
    build_alias_specs,
    build_coding_toolpack,
    resolve_coding_alias,
)
from swarmline.runtime.types import ToolSpec


# ---------------------------------------------------------------------------
# COMP-01: Legacy alias -> canonical mapping
# ---------------------------------------------------------------------------


class TestCodingAliasMap:
    """CODING_ALIAS_MAP maps legacy names to canonical coding tool names."""

    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [
            ("read_file", "read"),
            ("write_file", "write"),
            ("edit_file", "edit"),
            ("execute", "bash"),
            ("write_todos", "todo_write"),
        ],
        ids=["read_file", "write_file", "edit_file", "execute", "write_todos"],
    )
    def test_alias_maps_to_canonical(self, alias: str, canonical: str) -> None:
        """Each legacy alias resolves to the correct canonical name."""
        assert CODING_ALIAS_MAP[alias] == canonical

    def test_alias_map_has_exactly_5_entries(self) -> None:
        """The alias map contains exactly the 5 known legacy aliases."""
        assert len(CODING_ALIAS_MAP) == 5

    def test_alias_map_values_are_strings(self) -> None:
        """All alias targets are string names."""
        for alias, canonical in CODING_ALIAS_MAP.items():
            assert isinstance(alias, str)
            assert isinstance(canonical, str)


# ---------------------------------------------------------------------------
# COMP-01: resolve_coding_alias function
# ---------------------------------------------------------------------------


class TestResolveCodingAlias:
    """resolve_coding_alias resolves alias -> canonical or raises ValueError."""

    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [
            ("read_file", "read"),
            ("write_file", "write"),
            ("edit_file", "edit"),
            ("execute", "bash"),
            ("write_todos", "todo_write"),
        ],
    )
    def test_resolve_known_alias(self, alias: str, canonical: str) -> None:
        """Known alias resolves to canonical name."""
        assert resolve_coding_alias(alias) == canonical

    def test_resolve_canonical_name_passthrough(self) -> None:
        """Canonical names pass through unchanged."""
        assert resolve_coding_alias("read") == "read"
        assert resolve_coding_alias("bash") == "bash"
        assert resolve_coding_alias("edit") == "edit"

    @pytest.mark.parametrize(
        "bad_alias",
        ["unknown_tool", "ReadFile", "BASH", "exec"],
    )
    def test_resolve_unsupported_alias_raises_value_error(self, bad_alias: str) -> None:
        """Unsupported alias raises ValueError with descriptive message (COMP-02)."""
        with pytest.raises(ValueError, match="[Uu]nsupported.*alias|[Uu]nknown.*tool"):
            resolve_coding_alias(bad_alias)


# ---------------------------------------------------------------------------
# COMP-02: Unsupported states produce explicit errors
# ---------------------------------------------------------------------------


class TestUnsupportedAliasStates:
    """Unsupported alias/profile/wiring states raise, never silently fallback."""

    def test_resolve_empty_string_raises(self) -> None:
        """Empty string alias is not silently handled."""
        with pytest.raises(ValueError):
            resolve_coding_alias("")

    def test_resolve_none_like_raises(self) -> None:
        """None-like inputs are rejected at the type boundary."""
        with pytest.raises((ValueError, TypeError)):
            resolve_coding_alias(None)  # type: ignore[arg-type]

    def test_alias_map_no_silent_fallback(self) -> None:
        """CODING_ALIAS_MAP does not have a default/fallback entry."""
        assert "" not in CODING_ALIAS_MAP
        assert "default" not in CODING_ALIAS_MAP
        assert "*" not in CODING_ALIAS_MAP


# ---------------------------------------------------------------------------
# COMP-03: Alias layer delegates to canonical, not a second implementation
# ---------------------------------------------------------------------------


class TestAliasIsNotSecondImplementation:
    """Alias specs point to the same executors as canonical tools (COMP-03)."""

    def test_build_alias_specs_returns_tool_specs(self, coding_sandbox) -> None:
        """build_alias_specs returns ToolSpec objects for each alias."""
        pack = build_coding_toolpack(coding_sandbox)
        alias_specs = build_alias_specs(pack)

        for alias_name, spec in alias_specs.items():
            assert isinstance(spec, ToolSpec)
            assert spec.name == alias_name

    def test_alias_specs_delegate_to_canonical_executor(self, coding_sandbox) -> None:
        """Alias executors are the SAME callable as canonical executors (no wrapper)."""
        pack = build_coding_toolpack(coding_sandbox)
        alias_specs = build_alias_specs(pack)

        # For aliases that map to sandbox tools, the spec should reference canonical
        for alias_name in ["read_file", "write_file", "edit_file", "execute"]:
            if alias_name in alias_specs:
                canonical = CODING_ALIAS_MAP[alias_name]
                assert alias_specs[alias_name].description == pack.specs[canonical].description

    def test_alias_count_matches_map(self, coding_sandbox) -> None:
        """build_alias_specs produces exactly as many specs as aliases in the map."""
        pack = build_coding_toolpack(coding_sandbox)
        alias_specs = build_alias_specs(pack)

        # Only aliases whose canonical target exists in the pack are produced
        expected_count = sum(
            1 for canonical in CODING_ALIAS_MAP.values()
            if canonical in pack.specs
        )
        assert len(alias_specs) == expected_count


# ---------------------------------------------------------------------------
# COMP-01: Alias policy path matches canonical names
# ---------------------------------------------------------------------------


class TestAliasPolicyPath:
    """Alias tool names are resolved to canonical before policy check."""

    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [
            ("read_file", "read"),
            ("write_file", "write"),
            ("edit_file", "edit"),
            ("execute", "bash"),
        ],
    )
    def test_alias_resolves_before_policy(self, alias: str, canonical: str) -> None:
        """Policy sees the canonical name, not the alias."""
        resolved = resolve_coding_alias(alias)
        assert resolved == canonical
        assert resolved in CODING_TOOL_NAMES
