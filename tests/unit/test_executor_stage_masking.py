"""ToolExecutor stage-based soft masking (Stage 3, context-engineering-manus-parity).

Consumes the existing ``context.stable_prefix.mask_tools`` kernel primitive
(built in Stage 1, never wired to a runtime consumer until now) to gate WHICH
tool names may actually be invoked this turn, WITHOUT ever touching the tool
schema payload sent to the LLM (Manus ``browser_``/``shell_`` pattern: hide
availability, never change the wire schema — that would break the byte-stable
tools payload AGR-004 pins).

TDD: written before wiring `masked_tool_names` into `ToolExecutor.execute()`.
"""

from __future__ import annotations

import json
from typing import Any

from swarmline.runtime.thin.executor import ToolExecutor


async def _echo_tool(**args: Any) -> dict[str, Any]:
    return {"echo": args}


class TestToolExecutorStageMasking:
    """`masked_tool_names=None` (default) must be 100% backward compatible;
    when set, it is an ENABLED-name allowlist for this call only — it can
    never widen beyond `masked_tool_names`, and it never touches any tool's
    schema (name/description/parameters are not part of this call at all)."""

    async def test_none_masked_tool_names_allows_everything_backward_compat(
        self,
    ) -> None:
        """Default (no masking configured) — byte-identical to pre-Stage-3 executor."""
        executor = ToolExecutor(local_tools={"echo": _echo_tool})
        result = await executor.execute("echo", {"msg": "hi"}, masked_tool_names=None)
        data = json.loads(result)
        assert data["echo"]["msg"] == "hi"

    async def test_tool_in_masked_allowlist_executes_normally(self) -> None:
        executor = ToolExecutor(local_tools={"echo": _echo_tool})
        result = await executor.execute(
            "echo", {"msg": "hi"}, masked_tool_names=frozenset({"echo", "other"})
        )
        data = json.loads(result)
        assert data["echo"]["msg"] == "hi"

    async def test_tool_absent_from_masked_allowlist_is_soft_denied(self) -> None:
        """Not present at this stage -> a clear soft-deny error, tool never runs."""
        ran = False

        async def _spy_tool(**_: Any) -> dict[str, Any]:
            nonlocal ran
            ran = True
            return {"ok": True}

        executor = ToolExecutor(local_tools={"shell_exec": _spy_tool})
        result = await executor.execute(
            "shell_exec", {}, masked_tool_names=frozenset({"browser_click"})
        )
        data = json.loads(result)
        assert "error" in data
        assert "shell_exec" in data["error"]
        assert ran is False, "masked tool must never actually run"

    async def test_empty_masked_allowlist_denies_every_tool(self) -> None:
        executor = ToolExecutor(local_tools={"echo": _echo_tool})
        result = await executor.execute("echo", {}, masked_tool_names=frozenset())
        data = json.loads(result)
        assert "error" in data

    async def test_masking_runs_before_execution_not_after(self) -> None:
        """A masked-out tool call must be rejected BEFORE the tool body runs —
        confirms this is a gate, not a post-hoc audit."""
        call_count = 0

        async def _counting_tool(**_: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"ok": True}

        executor = ToolExecutor(local_tools={"dangerous": _counting_tool})
        await executor.execute(
            "dangerous", {}, masked_tool_names=frozenset({"safe_tool"})
        )
        assert call_count == 0
