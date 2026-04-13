"""Integration regressions for ThinRuntime wiring (phases 9/10/17)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_wiring import build_portable_runtime_plan
from swarmline.hooks.registry import HookRegistry
from swarmline.multi_agent.workspace_types import WorkspaceHandle, WorkspaceStrategy
from swarmline.policy.tool_policy import DefaultToolPolicy
from swarmline.runtime.factory import RuntimeFactory
from swarmline.runtime.thin.coding_profile import CodingProfileConfig
from swarmline.runtime.thin.subagent_tool import SubagentToolConfig
from swarmline.runtime.types import Message, RuntimeEvent


async def _final_llm_call(
    messages: list[dict[str, Any]],
    system_prompt: str,
    **kwargs: Any,
) -> str:
    del messages, system_prompt, kwargs
    return '{"type":"final","final_message":"ok"}'


async def _collect_events(runtime: Any, **kwargs: Any) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for event in runtime.run(**kwargs):
        events.append(event)
    return events


class _FakeWorkerRuntime:
    async def run(self, task: str) -> str:
        del task
        return "child done"


class _SessionStoreStub:
    async def load(self, agent_id: str, task_id: str) -> dict[str, Any]:
        return {"agent_id": agent_id, "task_id": task_id, "state": "active"}


class TestThinRuntimeWiring:
    def test_subagent_wiring_fail_fast_when_cwd_missing(self) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            subagent_config=SubagentToolConfig(),
        )
        with pytest.raises(ValueError, match="AgentConfig\\.cwd is required when subagent_config"):
            build_portable_runtime_plan(cfg, "thin")

    def test_thin_runtime_receives_subagent_inheritance_dependencies(
        self, tmp_path: Path
    ) -> None:
        hooks = HookRegistry()
        explicit_policy = DefaultToolPolicy(allowed_system_tools={"web_fetch"})
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd=str(tmp_path),
            hooks=hooks,
            tool_policy=explicit_policy,
            coding_profile=CodingProfileConfig(enabled=True, allow_host_execution=False),
            subagent_config=SubagentToolConfig(
                max_concurrent=2,
                max_worktrees=3,
                background_timeout=7.5,
            ),
        )

        plan = build_portable_runtime_plan(cfg, "thin")
        runtime = RuntimeFactory().create(
            config=plan.config,
            llm_call=_final_llm_call,
            **plan.create_kwargs,
        )

        orchestrator = runtime._subagent_orchestrator
        assert orchestrator is not None
        assert orchestrator._base_path == str(tmp_path)
        assert orchestrator._workspace is not None
        assert orchestrator._max_worktrees == 3
        assert orchestrator._background_timeout == 7.5
        assert orchestrator._hook_registry is hooks
        assert orchestrator._coding_profile == cfg.coding_profile
        assert "web_fetch" in orchestrator._tool_policy.allowed_system_tools
        assert "read" in orchestrator._tool_policy.allowed_system_tools

    @pytest.mark.asyncio
    async def test_spawn_agent_worktree_works_via_real_runtime_path(
        self, tmp_path: Path
    ) -> None:
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            cwd=str(tmp_path),
            coding_profile=CodingProfileConfig(enabled=True),
            subagent_config=SubagentToolConfig(max_concurrent=1, timeout_seconds=2.0),
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        runtime = RuntimeFactory().create(
            config=plan.config,
            llm_call=_final_llm_call,
            **plan.create_kwargs,
        )
        orch = runtime._subagent_orchestrator
        assert orch is not None

        async def _fake_create_worktree(
            agent_id: str, spec: Any
        ) -> WorkspaceHandle:
            del spec
            return WorkspaceHandle(
                workspace_id=f"ws-{agent_id}",
                agent_id="worker",
                task_id="t1",
                path=str(tmp_path / ".worktrees" / "worker_t1"),
                strategy=WorkspaceStrategy.GIT_WORKTREE,
                branch_name="swarmline/worker/t1",
            )

        async def _fake_cleanup_worktree(handle: WorkspaceHandle) -> None:
            del handle

        orch._create_worktree = _fake_create_worktree  # type: ignore[method-assign]
        orch._cleanup_worktree = _fake_cleanup_worktree  # type: ignore[method-assign]
        orch._create_runtime = lambda spec: _FakeWorkerRuntime()  # type: ignore[assignment]

        spawn_executor = runtime._executor._local_tools["spawn_agent"]
        raw = await spawn_executor({"task": "do work", "isolation": "worktree"})
        payload = json.loads(raw)

        assert payload["status"] == "completed"
        assert payload["result"] == "child done"

    @pytest.mark.asyncio
    async def test_coding_context_injected_into_runtime_prompt(
        self, tmp_path: Path
    ) -> None:
        captured: dict[str, Any] = {}

        async def _capture_llm(
            messages: list[dict[str, Any]],
            system_prompt: str,
            **kwargs: Any,
        ) -> str:
            del kwargs
            captured["messages"] = messages
            captured["system_prompt"] = system_prompt
            return '{"type":"final","final_message":"ok"}'

        cfg = AgentConfig(
            system_prompt="BASE_SYSTEM",
            runtime="thin",
            cwd=str(tmp_path),
            coding_profile=CodingProfileConfig(enabled=True, allow_host_execution=True),
            native_config={"task_session_store": _SessionStoreStub()},
        )
        plan = build_portable_runtime_plan(cfg, "thin", session_id="sess-42")
        runtime = RuntimeFactory().create(
            config=plan.config,
            llm_call=_capture_llm,
            **plan.create_kwargs,
        )

        events = await _collect_events(
            runtime,
            messages=[Message(role="user", content="Fix failing tests")],
            system_prompt=cfg.system_prompt,
            active_tools=plan.active_tools,
        )

        prompt = captured["system_prompt"]
        assert "## Coding Context" in prompt
        assert "## Current Task" in prompt
        assert "## Workspace" in prompt
        assert f"cwd: {tmp_path}" in prompt
        assert '"task_id": "sess-42"' in prompt
        assert any(event.is_final for event in events)

