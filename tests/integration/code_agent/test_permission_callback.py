"""Integration tests -- `on_permission_request` PreToolUse hook (Stage 3).

Verifies `code_agent._permission.build_permission_hook` correctly adapts the
public `PermissionCallback` into a `HookRegistry` entry driven by the REAL
`DefaultHookDispatcher` (reused infra, no fakes for the dispatch itself), and
that `CodeAgent` actually wires it into the runtime factory's `create_kwargs`
when `on_permission_request` is supplied.
"""

from __future__ import annotations

import json
from pathlib import Path

from swarmline.code_agent import CodeAgent, PermissionDecision
from swarmline.code_agent._permission import build_permission_hook
from swarmline.hooks.dispatcher import DefaultHookDispatcher

from .conftest import FakeRuntimeFactory


async def _build_real_tool_executor(cwd: Path, callback):
    """Build the REAL `ToolExecutor` a thin runtime would use for `cwd`,
    wired exactly like `CodeAgent` wires it (coding toolpack + capability
    tools + the `on_permission_request` PreToolUse hook + tool policy).

    Used to drive `write`/`read` through the actual production dispatch
    path (`ToolExecutor.execute`: pre-tool hook -> policy -> local tool),
    so "deny blocks the tool, no side effect" is proven against a REAL
    filesystem effect, not just the hook's own decision object.
    """
    from swarmline.agent.runtime_wiring import build_portable_runtime_plan
    from swarmline.runtime.thin.executor import ToolExecutor

    agent = CodeAgent(model="sonnet", cwd=str(cwd), on_permission_request=callback)
    plan = build_portable_runtime_plan(
        agent._config, "thin", runtime_factory=agent._factory
    )
    plan = agent._augment_plan(plan)
    return ToolExecutor(
        local_tools=plan.create_kwargs["tool_executors"],
        hook_dispatcher=DefaultHookDispatcher(plan.create_kwargs["hook_registry"]),
        tool_policy=plan.create_kwargs.get("tool_policy"),
    )


class TestPermissionHookWiredIntoRuntimeFactory:
    async def test_permission_hook_reaches_runtime_factory_create_kwargs(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        async def _allow_everything(tool_name: str, tool_input: dict) -> bool:
            return True

        agent = CodeAgent(
            model="sonnet",
            cwd=str(tmp_path),
            on_permission_request=_allow_everything,
            runtime_factory=fake_runtime_factory,
        )

        async for _event in agent.run("hi"):
            pass

        create_kwargs = fake_runtime_factory.create_calls[0]
        assert create_kwargs.get("hook_registry") is not None
        dispatcher = DefaultHookDispatcher(create_kwargs["hook_registry"])
        decision = await dispatcher.dispatch_pre_tool("write", {"path": "x.txt"})
        assert decision.action == "allow"

    async def test_no_callback_means_no_permission_hook_registered(
        self, tmp_path: Path, fake_runtime_factory: FakeRuntimeFactory
    ) -> None:
        """`on_permission_request=None` (the default) -- coding-profile
        policy still enforces, but no permission hook is added on top."""
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), runtime_factory=fake_runtime_factory
        )

        async for _event in agent.run("hi"):
            pass

        assert agent._permission_hook_registry is None


class TestPermissionCallbackDecisionNormalization:
    async def test_permission_callback_allow_lets_tool_execute(self) -> None:
        async def _cb(tool_name: str, tool_input: dict) -> PermissionDecision:
            return PermissionDecision.allow()

        dispatcher = DefaultHookDispatcher(build_permission_hook(_cb))

        decision = await dispatcher.dispatch_pre_tool("bash", {"command": "ls"})

        assert decision.action == "allow"

    async def test_permission_callback_returning_bool_true_allows(self) -> None:
        async def _cb(tool_name: str, tool_input: dict) -> bool:
            return True

        dispatcher = DefaultHookDispatcher(build_permission_hook(_cb))

        decision = await dispatcher.dispatch_pre_tool("read", {"path": "a.txt"})

        assert decision.action == "allow"

    async def test_permission_callback_returning_bool_false_blocks(self) -> None:
        async def _cb(tool_name: str, tool_input: dict) -> bool:
            return False

        dispatcher = DefaultHookDispatcher(build_permission_hook(_cb))

        decision = await dispatcher.dispatch_pre_tool("bash", {"command": "rm x"})

        assert decision.action == "block"

    async def test_permission_callback_deny_empty_reason_uses_generic_message(
        self,
    ) -> None:
        async def _cb(tool_name: str, tool_input: dict) -> PermissionDecision:
            return PermissionDecision(allowed=False, reason="")

        dispatcher = DefaultHookDispatcher(build_permission_hook(_cb))

        decision = await dispatcher.dispatch_pre_tool("bash", {"command": "ls"})

        assert decision.action == "block"
        assert decision.message  # non-empty generic fallback

    async def test_permission_callback_raises_fails_closed_blocks_tool(self) -> None:
        """A raising callback must BLOCK, not allow. `DefaultHookDispatcher`
        itself is fail-OPEN on a raising hook (logs + treats as allow) -- the
        adapter must catch the exception itself so the dispatcher never sees
        it raise, proving the fail-closed behavior is the adapter's, not an
        accidental byproduct of the dispatcher's own fail-open policy."""

        async def _boom(tool_name: str, tool_input: dict) -> bool:
            raise RuntimeError("callback exploded")

        dispatcher = DefaultHookDispatcher(build_permission_hook(_boom))

        decision = await dispatcher.dispatch_pre_tool("bash", {"command": "rm -rf /"})

        assert decision.action == "block"

    async def test_permission_callback_raises_does_not_leak_exception_text(
        self,
    ) -> None:
        """The block message must NOT echo the raw exception text -- a
        permission backend's exception may embed secrets/internal details
        (e.g. a credential lookup failure), and `HookResult.message` flows
        straight back into the tool-call transcript the model itself sees."""

        async def _boom(tool_name: str, tool_input: dict) -> bool:
            raise RuntimeError("db password is hunter2")

        dispatcher = DefaultHookDispatcher(build_permission_hook(_boom))

        decision = await dispatcher.dispatch_pre_tool("bash", {"command": "ls"})

        assert decision.action == "block"
        assert "hunter2" not in (decision.message or "")

    async def test_permission_callback_unexpected_return_type_fails_closed(
        self,
    ) -> None:
        """A callback that violates its own `bool | PermissionDecision`
        contract (e.g. returns a string) must fail CLOSED, not be coerced
        through Python truthiness -- a non-empty string like `"false"` or a
        non-empty dict is truthy and would otherwise silently become
        "allow"."""

        async def _cb(tool_name: str, tool_input: dict) -> str:
            return "false"  # truthy in Python -- must NOT be treated as allow

        dispatcher = DefaultHookDispatcher(build_permission_hook(_cb))

        decision = await dispatcher.dispatch_pre_tool("bash", {"command": "ls"})

        assert decision.action == "block"


class TestPermissionCallbackRealToolExecutorSideEffect:
    """Drives the permission hook through the REAL `ToolExecutor` (the exact
    production dispatch path: pre-tool hook -> policy -> local tool), proving
    "deny blocks the tool" against an ACTUAL filesystem effect -- not just
    the hook's own decision object."""

    async def test_allow_lets_write_tool_create_the_file(self, tmp_path: Path) -> None:
        async def _allow(tool_name: str, tool_input: dict) -> bool:
            return True

        executor = await _build_real_tool_executor(tmp_path, _allow)

        write_result = json.loads(
            await executor.execute("write", {"path": "note.txt", "content": "hi"})
        )
        assert write_result["status"] == "ok"

        read_result = json.loads(await executor.execute("read", {"path": "note.txt"}))
        assert read_result["content"] == "hi"

    async def test_deny_blocks_write_tool_and_file_is_never_created(
        self, tmp_path: Path
    ) -> None:
        """Denies ONLY `write` (allows everything else, including the
        follow-up `read`) -- so the `read` result genuinely reflects
        filesystem state instead of also being blocked by the same
        callback."""

        async def _deny_write_only(tool_name: str, tool_input: dict) -> bool:
            return tool_name != "write"

        executor = await _build_real_tool_executor(tmp_path, _deny_write_only)

        write_result = json.loads(
            await executor.execute("write", {"path": "note.txt", "content": "hi"})
        )
        assert "error" in write_result

        read_result = json.loads(await executor.execute("read", {"path": "note.txt"}))
        assert read_result["status"] == "error"  # file was never created
