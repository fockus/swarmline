"""Integration tests -- capability tools wired into the facade (Stage 3).

Verifies `CodeAgent` merges the governance/workspace/scratchpad/code_intel
capability tools (`code_agent._tools.assemble_capability_tools`) into the
portable runtime plan's `active_tools` + `tool_executors`, on top of the
coding toolpack Stage 2 already wires. Fully offline: exercises the scripted
`FakeRuntimeFactory` (see `conftest.py`), no live LLM call.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from swarmline.code_agent import CodeAgent
from swarmline.code_agent._tools import assemble_capability_tools

from .conftest import FakeRuntimeFactory


async def _git(cwd: Path, *args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(err.decode())


class TestCapabilityToolPresentInActiveTools:
    @pytest.mark.parametrize(
        "tool_name",
        [
            "check_permission",
            "request_approval",
            "get_audit",
            "redact_secrets",
            "git_status",
            "run_verification",
            "scratch_write",
            "scratch_read",
            "repo_map",
            "impact_analysis",
        ],
    )
    async def test_capability_tool_present_in_active_tools(
        self,
        tmp_path: Path,
        fake_runtime_factory: FakeRuntimeFactory,
        tool_name: str,
    ) -> None:
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )

        async for _event in agent.run("hi"):
            pass

        active_tool_names = {
            spec.name
            for spec in fake_runtime_factory.created[0].run_kwargs["active_tools"]
        }
        assert tool_name in active_tool_names

    async def test_capability_tool_executors_reach_factory_create(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )

        async for _event in agent.run("hi"):
            pass

        executor_names = set(fake_runtime_factory.create_calls[0]["tool_executors"])
        assert {
            "check_permission",
            "git_status",
            "scratch_write",
            "repo_map",
        } <= executor_names

    async def test_coding_tool_still_present_alongside_capability_tools(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        """Stage 3 augments the plan, it never displaces the Stage 2 coding
        toolpack (`read`/`write`/`bash`)."""
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )

        async for _event in agent.run("hi"):
            pass

        active_tool_names = {
            spec.name
            for spec in fake_runtime_factory.created[0].run_kwargs["active_tools"]
        }
        assert {
            "read",
            "write",
            "bash",
            "git_status",
            "scratch_write",
        } <= active_tool_names


class TestWorkspaceToolsBoundToCwd:
    async def test_workspace_tools_built_for_cwd(self, tmp_path: Path) -> None:
        """`git_status` reflects the real repo rooted at `cwd`, not the host
        process's own working directory -- proves the `WorkspaceSession` the
        workspace tools close over is actually bound to `cwd`."""
        await _git(tmp_path, "init", "-q")
        (tmp_path / "untracked.txt").write_text("hello")

        _specs, executors = assemble_capability_tools(str(tmp_path))
        result = json.loads(await executors["git_status"]({}))

        assert result["success"] is True
        assert any("untracked.txt" in f for f in result["changed_files"])


class TestCapabilityToolPrecedence:
    async def test_existing_coding_tool_wins_over_capability_tool_on_name_collision(
        self, tmp_path: Path
    ) -> None:
        """If a name already present in the plan's active tools collides
        with a capability tool name, the EXISTING (coding-profile) entry
        wins -- the capability tool is skipped, never overwrites it."""
        import dataclasses

        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))
        plan = build_portable_runtime_plan(
            agent._config, "thin", runtime_factory=agent._factory
        )

        async def _sentinel_executor(**_kwargs: object) -> str:
            return "sentinel"

        from swarmline.runtime.types import ToolSpec

        sentinel_spec = ToolSpec(
            name="git_status", description="pre-existing sentinel", parameters={}
        )
        plan = dataclasses.replace(
            plan,
            active_tools=[*plan.active_tools, sentinel_spec],
            create_kwargs={
                **plan.create_kwargs,
                "tool_executors": {
                    **plan.create_kwargs.get("tool_executors", {}),
                    "git_status": _sentinel_executor,
                },
            },
        )

        augmented = agent._augment_plan(plan)

        git_status_specs = [
            spec for spec in augmented.active_tools if spec.name == "git_status"
        ]
        assert len(git_status_specs) == 1
        assert git_status_specs[0] is sentinel_spec
        assert (
            augmented.create_kwargs["tool_executors"]["git_status"]
            is _sentinel_executor
        )
