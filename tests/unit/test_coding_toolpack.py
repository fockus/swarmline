"""Tests for CodingToolPack + build_coding_toolpack — CADG-02, CADG-03.

RED phase: tests define the contract for the canonical coding tool pack.
build_coding_toolpack raises NotImplementedError until Task 2.
"""

from __future__ import annotations

import pytest

from swarmline.runtime.thin.coding_toolpack import (
    CODING_SANDBOX_TOOL_NAMES,
    CODING_TOOL_NAMES,
    CodingToolPack,
    build_coding_toolpack,
)
from swarmline.runtime.types import ToolSpec


# ---------------------------------------------------------------------------
# CADG-02: name parity — visible tool surface == executable tool surface
# ---------------------------------------------------------------------------


class TestCodingToolPackContract:
    """CodingToolPack guarantees spec/executor name parity."""

    def test_tool_names_constant_has_10_tools(self) -> None:
        """Canonical set = 8 sandbox + 2 todo tools."""
        assert len(CODING_TOOL_NAMES) == 10
        expected = {
            "read", "write", "edit", "multi_edit", "bash", "ls", "glob", "grep",
            "todo_read", "todo_write",
        }
        assert CODING_TOOL_NAMES == expected

    def test_sandbox_tool_names_has_8_tools(self) -> None:
        """Sandbox subset = read, write, edit, multi_edit, bash, ls, glob, grep."""
        assert len(CODING_SANDBOX_TOOL_NAMES) == 8
        expected = {"read", "write", "edit", "multi_edit", "bash", "ls", "glob", "grep"}
        assert CODING_SANDBOX_TOOL_NAMES == expected

    def test_pack_tool_names_match_specs_and_executors(self) -> None:
        """CodingToolPack.tool_names reflects specs keys."""
        specs = {
            "read": ToolSpec(name="read", description="r", parameters={}),
            "bash": ToolSpec(name="bash", description="b", parameters={}),
        }

        async def noop(args: dict) -> str:
            return ""

        executors = {"read": noop, "bash": noop}
        pack = CodingToolPack(specs=specs, executors=executors)
        assert pack.tool_names == frozenset({"read", "bash"})

    def test_pack_is_frozen(self) -> None:
        """CodingToolPack is a frozen dataclass."""
        import dataclasses

        pack = CodingToolPack(specs={}, executors={})
        assert dataclasses.is_dataclass(pack)
        with pytest.raises(dataclasses.FrozenInstanceError):
            pack.specs = {}  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CADG-03: build_coding_toolpack uses create_sandbox_tools
# ---------------------------------------------------------------------------


class TestBuildCodingToolpack:
    """build_coding_toolpack contract — will fail until Task 2 implements it."""

    def test_raises_on_none_sandbox(self) -> None:
        """build_coding_toolpack(None) raises ValueError."""
        with pytest.raises(ValueError, match="sandbox is required"):
            build_coding_toolpack(None)

    def test_returns_coding_tool_pack(self, coding_sandbox) -> None:
        """build_coding_toolpack(sandbox) returns CodingToolPack with 8 sandbox tools."""
        pack = build_coding_toolpack(coding_sandbox)

        assert isinstance(pack, CodingToolPack)
        assert pack.tool_names == CODING_SANDBOX_TOOL_NAMES

    def test_spec_executor_name_parity(self, coding_sandbox) -> None:
        """Spec keys == executor keys (CADG-02)."""
        pack = build_coding_toolpack(coding_sandbox)

        assert set(pack.specs.keys()) == set(pack.executors.keys())

    def test_all_specs_are_tool_spec(self, coding_sandbox) -> None:
        """Every spec is a ToolSpec instance."""
        pack = build_coding_toolpack(coding_sandbox)

        for name, spec in pack.specs.items():
            assert isinstance(spec, ToolSpec), f"{name} is not ToolSpec"

    def test_all_executors_are_callable(self, coding_sandbox) -> None:
        """Every executor is callable."""
        pack = build_coding_toolpack(coding_sandbox)

        for name, executor in pack.executors.items():
            assert callable(executor), f"{name} is not callable"

    def test_no_extra_tools_beyond_canonical(self, coding_sandbox) -> None:
        """Pack contains exactly CODING_SANDBOX_TOOL_NAMES — no extras."""
        pack = build_coding_toolpack(coding_sandbox)

        assert pack.tool_names == CODING_SANDBOX_TOOL_NAMES
        # No thin-specific aliases (read_file, write_file, execute, etc.)
        assert "read_file" not in pack.specs
        assert "execute" not in pack.specs
        assert "write_file" not in pack.specs

    def test_missing_tool_in_sandbox_raises_runtime_error(self) -> None:
        """RuntimeError when create_sandbox_tools doesn't provide a canonical tool."""
        from unittest.mock import patch

        # Provide 7 of 8 tools — missing "grep"
        available = sorted(CODING_TOOL_NAMES - {"grep"})
        incomplete_specs = {
            name: ToolSpec(name=name, description="stub", parameters={})
            for name in available
        }

        async def noop(args: dict) -> str:
            return ""

        incomplete_executors = {name: noop for name in available}

        with patch(
            "swarmline.tools.builtin.create_sandbox_tools",
        ) as mock_fn:
            mock_fn.return_value = (incomplete_specs, incomplete_executors)
            with pytest.raises(RuntimeError, match="grep.*not found"):
                build_coding_toolpack("fake_sandbox")

    def test_specs_and_executors_immutable_after_construction(
        self, coding_sandbox,
    ) -> None:
        """CodingToolPack specs/executors are read-only MappingProxy."""
        pack = build_coding_toolpack(coding_sandbox)

        with pytest.raises(TypeError):
            pack.specs["injected"] = ToolSpec(  # type: ignore[index]
                name="injected", description="x", parameters={},
            )

        with pytest.raises(TypeError):
            pack.executors["injected"] = lambda args: ""  # type: ignore[index]
