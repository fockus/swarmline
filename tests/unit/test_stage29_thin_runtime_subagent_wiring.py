"""Stage 29 — ThinRuntime never wires the ready-made ToolsetPolicy/depth seam.

Audit finding: `create_subagent_executor` already accepts `toolset_policy`,
`spawn_role`, and `current_depth` (REQ-ORC-040/041/042, RCA-SEC-01), but
`ThinRuntime`'s two production call sites (`__init__`'s initial executor and
`run()`'s post-hoc "updated_executor") never passed them — `toolset_policy`
was always `None` (legacy full inheritance) and `current_depth` was always
hardcoded `0`, so the depth guard could never trip for any real nesting.

These tests exercise `ThinRuntime` directly (not through
`AgentConfig`/`build_portable_runtime_plan` — those files are out of scope
for this stage, see plan Этап 29 rider) and prove the constructor-level
`toolset_policy=`/`spawn_role=`/`current_depth=` parameters actually reach
the executor that gets registered as the `spawn_agent` local tool.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from swarmline.domain_types import ToolSpec
from swarmline.orchestration.subagent_types import (
    SubagentResult,
    SubagentSpec,
    SubagentStatus,
)
from swarmline.policy.toolset_policy import RESEARCHER_TOOLS, ToolsetPolicy
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.thin.subagent_tool import SubagentToolConfig
from swarmline.runtime.types import Message, RuntimeConfig


async def _noop_llm(**kw: object) -> dict[str, object]:
    del kw
    return {"content": "ok", "tool_calls": []}


async def _final_llm_call(
    messages: list[dict[str, Any]],
    system_prompt: str,
    **kwargs: Any,
) -> str:
    del messages, system_prompt, kwargs
    return '{"type":"final","final_message":"ok"}'


@pytest.fixture
def thin_config() -> RuntimeConfig:
    return RuntimeConfig(runtime_name="thin")


def _mock_spawn_wait(
    rt: ThinRuntime, *, output: str = "done", agent_id: str = "agent-1"
) -> AsyncMock:
    """Patch the SAME orchestrator instance ThinRuntime already built (its
    spawn_agent executor closure captured it by reference at __init__ time —
    re-pointing `rt._subagent_orchestrator` would not affect that closure)."""
    spawn_mock = AsyncMock(return_value=agent_id)
    rt._subagent_orchestrator.spawn = spawn_mock  # type: ignore[union-attr]
    rt._subagent_orchestrator.wait = AsyncMock(  # type: ignore[union-attr]
        return_value=SubagentResult(
            agent_id=agent_id, status=SubagentStatus(state="completed"), output=output
        )
    )
    return spawn_mock


# ---------------------------------------------------------------------------
# ToolsetPolicy default-deny reaches the spawn path via ThinRuntime
# (test_child_toolset_default_deny_via_toolset_policy)
# ---------------------------------------------------------------------------


class TestToolsetPolicyWiredIntoThinRuntimeSpawnPath:
    """`ThinRuntime(toolset_policy=..., spawn_role=...)` must actually reach
    `create_subagent_executor` — a child spawned via the LLM-facing
    `spawn_agent` tool does not inherit the parent's `finalize`/`spawn_agent`
    (or any other out-of-policy tool)."""

    async def test_child_does_not_inherit_finalize_or_spawn_agent(
        self, thin_config: RuntimeConfig
    ) -> None:
        cfg = SubagentToolConfig()
        rt = ThinRuntime(
            config=thin_config,
            llm_call=_final_llm_call,
            subagent_config=cfg,
            toolset_policy=ToolsetPolicy.researcher(),
            spawn_role="researcher",
        )
        # Patched BEFORE run(): run()'s "updated_executor" closure captures
        # `self._subagent_orchestrator` by reference, and the object identity
        # is stable across __init__/run(), so mutating its methods here is
        # visible to whichever closure ends up registered afterwards.
        _mock_spawn_wait(rt)

        # Drive run() once so the "updated_executor" branch (which folds in
        # active_tools — including a custom "finalize" tool and "bash", as a
        # real host's toolset would) registers the policy-aware executor.
        active_tools = [
            ToolSpec(
                name="finalize", description="finalize", parameters={"type": "object"}
            ),
            ToolSpec(name="bash", description="bash", parameters={"type": "object"}),
            ToolSpec(name="read", description="read", parameters={"type": "object"}),
            ToolSpec(
                name="web_search",
                description="web_search",
                parameters={"type": "object"},
            ),
        ]
        async for _event in rt.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=active_tools,
        ):
            break

        executor = rt._executor._local_tools["spawn_agent"]
        raw = await executor({"task": "investigate the incident"})
        payload = json.loads(raw)

        assert payload["status"] == "completed"
        spec: SubagentSpec = rt._subagent_orchestrator.spawn.call_args.args[0]  # type: ignore[union-attr]
        child_names = {t.name for t in spec.tools}
        assert "finalize" not in child_names
        assert "spawn_agent" not in child_names
        assert "bash" not in child_names
        assert child_names <= RESEARCHER_TOOLS
        assert child_names  # non-empty: the parent's active_tools overlap RESEARCHER_TOOLS ("read"/"web_search" etc would too)

    async def test_no_toolset_policy_preserves_legacy_full_inheritance(
        self, thin_config: RuntimeConfig
    ) -> None:
        """Regression: omitting toolset_policy (default None) is byte-identical
        to pre-Stage-29 behavior — full parent toolset inherited."""
        cfg = SubagentToolConfig()
        rt = ThinRuntime(config=thin_config, llm_call=_noop_llm, subagent_config=cfg)
        _mock_spawn_wait(rt)

        executor = rt._executor._local_tools["spawn_agent"]
        raw = await executor({"task": "do X"})
        payload = json.loads(raw)

        assert payload["status"] == "completed"
        spec: SubagentSpec = rt._subagent_orchestrator.spawn.call_args.args[0]  # type: ignore[union-attr]
        # No sandbox => no builtin specs => initial parent_tools is empty;
        # legacy inheritance of an empty set is still legacy (no error, no gate).
        assert spec.tools == []


# ---------------------------------------------------------------------------
# Fix-cycle 2, MAJOR-1: secret_boundary reaches the ThinRuntime spawn_agent
# path (previously ThinRuntime never threaded it into either
# create_subagent_executor call site — GPT-5.5 review finding).
# ---------------------------------------------------------------------------


class TestSecretBoundaryWiredIntoThinRuntimeSpawnPath:
    """`ThinRuntime(secret_boundary=...)` must reach `create_subagent_executor`
    — a leaking child return is redacted in the tool-JSON handed back to the
    LLM-driven `spawn_agent` caller, not just for direct
    `create_subagent_executor(...)` callers (e.g. taskloom's dispatch_toolset)."""

    async def test_secret_pattern_in_child_output_is_redacted(
        self, thin_config: RuntimeConfig
    ) -> None:
        from swarmline.governance.secret_boundary import SecretBoundaryManager

        cfg = SubagentToolConfig()
        rt = ThinRuntime(
            config=thin_config,
            llm_call=_noop_llm,
            subagent_config=cfg,
            secret_boundary=SecretBoundaryManager(),
        )
        leaking_output = "here is the key: sk-abcdefghijklmnopqrstuvwxyz0123456789"
        _mock_spawn_wait(rt, output=leaking_output)

        executor = rt._executor._local_tools["spawn_agent"]
        raw = await executor({"task": "investigate"})
        payload = json.loads(raw)

        assert payload["status"] == "completed"
        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in payload["result"]
        assert "[REDACTED:api_key]" in payload["result"]

    async def test_no_secret_boundary_preserves_legacy_raw_passthrough(
        self, thin_config: RuntimeConfig
    ) -> None:
        """Regression: omitting secret_boundary (default None) is byte-identical."""
        cfg = SubagentToolConfig()
        rt = ThinRuntime(config=thin_config, llm_call=_noop_llm, subagent_config=cfg)
        leaking_output = "here is the key: sk-abcdefghijklmnopqrstuvwxyz0123456789"
        _mock_spawn_wait(rt, output=leaking_output)

        executor = rt._executor._local_tools["spawn_agent"]
        raw = await executor({"task": "investigate"})
        payload = json.loads(raw)

        assert payload["result"] == leaking_output


# ---------------------------------------------------------------------------
# Fix-cycle 2, MAJOR-2a: secret_boundary reaches the ThinRuntime monitor_agent
# path (create_monitor_executor previously had no secret_boundary parameter
# at all — a parent could bypass a redacted spawn_agent return by calling
# monitor_agent for the same agent_id and getting the raw output).
# ---------------------------------------------------------------------------


class TestSecretBoundaryWiredIntoThinRuntimeMonitorPath:
    """`ThinRuntime(secret_boundary=...)` must also reach `monitor_agent`."""

    async def test_secret_pattern_in_monitored_output_is_redacted(
        self, thin_config: RuntimeConfig
    ) -> None:
        from swarmline.governance.secret_boundary import SecretBoundaryManager
        from swarmline.orchestration.subagent_types import SubagentStatus

        cfg = SubagentToolConfig()
        rt = ThinRuntime(
            config=thin_config,
            llm_call=_noop_llm,
            subagent_config=cfg,
            secret_boundary=SecretBoundaryManager(),
        )
        leaking_output = "here is the key: sk-abcdefghijklmnopqrstuvwxyz0123456789"
        leaking_error = "crashed: token=sk-abcdefghijklmnopqrstuvwxyz0123456789"
        rt._subagent_orchestrator.get_status = AsyncMock(  # type: ignore[union-attr]
            return_value=SubagentStatus(
                state="completed", error=leaking_error, result=leaking_output
            )
        )
        rt._subagent_orchestrator.get_output = lambda _agent_id: leaking_output  # type: ignore[union-attr]

        monitor_executor = rt._executor._local_tools["monitor_agent"]
        raw = await monitor_executor({"agent_id": "agent-1"})
        payload = json.loads(raw)

        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in payload["output"]
        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in payload["error"]
        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in payload["result"]
        assert "[REDACTED:api_key]" in payload["output"]

    async def test_no_secret_boundary_preserves_legacy_monitor_passthrough(
        self, thin_config: RuntimeConfig
    ) -> None:
        """Regression: omitting secret_boundary (default None) is byte-identical."""
        from swarmline.orchestration.subagent_types import SubagentStatus

        cfg = SubagentToolConfig()
        rt = ThinRuntime(config=thin_config, llm_call=_noop_llm, subagent_config=cfg)
        leaking_output = "here is the key: sk-abcdefghijklmnopqrstuvwxyz0123456789"
        rt._subagent_orchestrator.get_status = AsyncMock(  # type: ignore[union-attr]
            return_value=SubagentStatus(state="completed")
        )
        rt._subagent_orchestrator.get_output = lambda _agent_id: leaking_output  # type: ignore[union-attr]

        monitor_executor = rt._executor._local_tools["monitor_agent"]
        raw = await monitor_executor({"agent_id": "agent-1"})
        payload = json.loads(raw)

        assert payload["output"] == leaking_output


# ---------------------------------------------------------------------------
# current_depth is real, not hardcoded 0
# (test_depth_increments_on_spawn_and_guard_trips_at_max)
# ---------------------------------------------------------------------------


class TestCurrentDepthWiredIntoThinRuntimeSpawnPath:
    """`ThinRuntime(current_depth=N)` reaches `create_subagent_executor` —
    depth increments on spawn, and the guard is reachable/trips at max."""

    async def test_depth_increments_on_spawn(self, thin_config: RuntimeConfig) -> None:
        cfg = SubagentToolConfig(max_depth=5)
        rt = ThinRuntime(
            config=thin_config, llm_call=_noop_llm, subagent_config=cfg, current_depth=1
        )
        _mock_spawn_wait(rt)

        executor = rt._executor._local_tools["spawn_agent"]
        raw = await executor({"task": "go"})
        payload = json.loads(raw)

        assert payload["status"] == "completed"
        spec: SubagentSpec = rt._subagent_orchestrator.spawn.call_args.args[0]  # type: ignore[union-attr]
        assert (
            spec.depth == 2
        )  # current_depth(1) + 1 — a REAL increment, not a fixed 0-derived value

    async def test_guard_trips_when_runtime_is_constructed_at_max_depth(
        self, thin_config: RuntimeConfig
    ) -> None:
        """A ThinRuntime built with current_depth == max_depth refuses to spawn —
        this is UNREACHABLE pre-Stage-29 (current_depth was always hardcoded 0)."""
        cfg = SubagentToolConfig(max_depth=2)
        rt = ThinRuntime(
            config=thin_config, llm_call=_noop_llm, subagent_config=cfg, current_depth=2
        )
        spawn_mock = _mock_spawn_wait(rt)

        executor = rt._executor._local_tools["spawn_agent"]
        raw = await executor({"task": "go deeper"})
        payload = json.loads(raw)

        assert payload["status"] == "error"
        assert "depth" in payload["error"].lower()
        spawn_mock.assert_not_called()

    async def test_default_current_depth_zero_preserves_legacy_behavior(
        self, thin_config: RuntimeConfig
    ) -> None:
        """Regression: omitting current_depth (default 0) behaves as before."""
        cfg = SubagentToolConfig(max_depth=3)
        rt = ThinRuntime(config=thin_config, llm_call=_noop_llm, subagent_config=cfg)
        _mock_spawn_wait(rt)

        executor = rt._executor._local_tools["spawn_agent"]
        raw = await executor({"task": "go"})
        payload = json.loads(raw)

        assert payload["status"] == "completed"
        spec: SubagentSpec = rt._subagent_orchestrator.spawn.call_args.args[0]  # type: ignore[union-attr]
        assert spec.depth == 1


# ---------------------------------------------------------------------------
# thin_subagent.py: the worker threads spec.depth into the child ThinRuntime
# ---------------------------------------------------------------------------


class TestThinWorkerRuntimeThreadsSpecDepthToChildRuntime:
    """`_ThinWorkerRuntime.run()` passes `current_depth=self._spec.depth` when
    constructing the child `ThinRuntime` — closing the loop so a depth
    recorded on a `SubagentSpec` (by `create_subagent_executor`) is not
    silently dropped on the next hop."""

    async def test_worker_run_passes_spec_depth_as_child_current_depth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.orchestration import thin_subagent as thin_subagent_module

        captured: dict[str, Any] = {}

        class _FakeChildRuntime:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

            def run(self, **_kwargs: Any) -> Any:
                async def _gen() -> Any:
                    from swarmline.domain_types import RuntimeEvent

                    yield RuntimeEvent.final("child done")

                return _gen()

        monkeypatch.setattr(
            thin_subagent_module,
            "ThinRuntime",
            lambda **kwargs: _FakeChildRuntime(**kwargs),
        )

        spec = SubagentSpec(name="w", system_prompt="p", depth=2)
        worker = thin_subagent_module._ThinWorkerRuntime(
            spec=spec,
            llm_call=None,
            local_tools={},
            mcp_servers=None,
            runtime_config=RuntimeConfig(runtime_name="thin"),
        )

        output = await worker.run("task")

        assert captured["current_depth"] == 2
        assert output == "child done"

    async def test_worker_run_defaults_to_zero_when_spec_has_no_depth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from swarmline.orchestration import thin_subagent as thin_subagent_module

        captured: dict[str, Any] = {}

        class _FakeChildRuntime:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

            def run(self, **_kwargs: Any) -> Any:
                async def _gen() -> Any:
                    from swarmline.domain_types import RuntimeEvent

                    yield RuntimeEvent.final("child done")

                return _gen()

        monkeypatch.setattr(
            thin_subagent_module,
            "ThinRuntime",
            lambda **kwargs: _FakeChildRuntime(**kwargs),
        )

        spec = SubagentSpec(name="w", system_prompt="p")  # depth defaults to 0
        worker = thin_subagent_module._ThinWorkerRuntime(
            spec=spec,
            llm_call=None,
            local_tools={},
            mcp_servers=None,
            runtime_config=RuntimeConfig(runtime_name="thin"),
        )

        await worker.run("task")

        assert captured["current_depth"] == 0
