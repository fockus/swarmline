"""Tests for session-level hooks: file.edited, session.idle, session.compacted.

Covers REQ-RCA-030 (3 session events dispatched at lifecycle points)
and REQ-RCA-031 (fail-open: raising callback is logged, run continues).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from swarmline.compaction import CompactionConfig
from swarmline.hooks.dispatcher import DefaultHookDispatcher
from swarmline.hooks.registry import HookRegistry
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeEvent,
    ToolSpec,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _MockLLM:
    """Returns pre-set responses in order; falls back to final on exhaustion."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def __call__(
        self, messages: list[dict[str, Any]], system_prompt: str, **kwargs: Any
    ) -> str:
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return json.dumps({"type": "final", "final_message": "fallback"})


def _final(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


def _tool_call(name: str, args: dict[str, Any] | None = None) -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "tool": {"name": name, "args": args or {}, "correlation_id": "c1"},
            "assistant_message": "",
        }
    )


async def _collect(
    runtime: ThinRuntime,
    text: str = "test",
    tools: list[ToolSpec] | None = None,
    mode_hint: str | None = None,
) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for ev in runtime.run(
        messages=[Message(role="user", content=text)],
        system_prompt="System",
        active_tools=tools or [],
        mode_hint=mode_hint,
    ):
        events.append(ev)
    return events


async def _noop_tool(args: dict[str, Any]) -> str:
    return json.dumps({"ok": True})


_EDIT_TOOL = ToolSpec(
    name="edit",
    description="Edit a file",
    parameters={"type": "object", "properties": {}},
)

_WRITE_TOOL = ToolSpec(
    name="write",
    description="Write a file",
    parameters={"type": "object", "properties": {}},
)

_ECHO_TOOL = ToolSpec(
    name="echo",
    description="Echo a value",
    parameters={"type": "object", "properties": {}},
)


# ===========================================================================
# 1. HookRegistry — registration methods
# ===========================================================================


class TestSessionHookRegistration:
    """HookRegistry exposes on_file_edited / on_session_idle / on_session_compacted."""

    def test_on_file_edited_registers_under_file_edited_key(self) -> None:
        reg = HookRegistry()

        async def cb(**kwargs: Any) -> None: ...

        reg.on_file_edited(cb)
        hooks = reg.get_hooks("file.edited")
        assert len(hooks) == 1
        assert hooks[0].callback is cb

    def test_on_session_idle_registers_under_session_idle_key(self) -> None:
        reg = HookRegistry()

        async def cb(**kwargs: Any) -> None: ...

        reg.on_session_idle(cb)
        hooks = reg.get_hooks("session.idle")
        assert len(hooks) == 1
        assert hooks[0].callback is cb

    def test_on_session_compacted_registers_under_session_compacted_key(self) -> None:
        reg = HookRegistry()

        async def cb(**kwargs: Any) -> None: ...

        reg.on_session_compacted(cb)
        hooks = reg.get_hooks("session.compacted")
        assert len(hooks) == 1
        assert hooks[0].callback is cb

    def test_multiple_file_edited_hooks_accumulate(self) -> None:
        reg = HookRegistry()

        async def cb1(**kwargs: Any) -> None: ...

        async def cb2(**kwargs: Any) -> None: ...

        reg.on_file_edited(cb1)
        reg.on_file_edited(cb2)
        assert len(reg.get_hooks("file.edited")) == 2

    def test_no_session_hooks_returns_empty_list(self) -> None:
        reg = HookRegistry()
        assert reg.get_hooks("file.edited") == []
        assert reg.get_hooks("session.idle") == []
        assert reg.get_hooks("session.compacted") == []


# ===========================================================================
# 2. DefaultHookDispatcher.dispatch_session_event — unit tests
# ===========================================================================


class TestDispatchSessionEvent:
    """dispatch_session_event: deliver to registered callbacks, fail-open on raise."""

    async def test_registered_callback_receives_event_and_payload_kwargs(
        self,
    ) -> None:
        received: list[tuple[str, dict[str, Any]]] = []

        async def cb(event: str, **kwargs: Any) -> None:
            received.append((event, dict(kwargs)))

        reg = HookRegistry()
        reg.on_file_edited(cb)
        dispatcher = DefaultHookDispatcher(reg)
        await dispatcher.dispatch_session_event("file.edited", {"path": "/src/foo.py"})

        assert len(received) == 1
        assert received[0][0] == "file.edited"
        assert received[0][1].get("path") == "/src/foo.py"

    async def test_no_hooks_registered_returns_without_exception(self) -> None:
        reg = HookRegistry()
        dispatcher = DefaultHookDispatcher(reg)
        # None of these should raise
        await dispatcher.dispatch_session_event("file.edited", {"path": "/x.py"})
        await dispatcher.dispatch_session_event("session.idle", {})
        await dispatcher.dispatch_session_event("session.compacted", {})

    async def test_multiple_callbacks_all_invoked_in_order(self) -> None:
        order: list[str] = []

        async def cb_first(event: str, **kwargs: Any) -> None:
            order.append("first")

        async def cb_second(event: str, **kwargs: Any) -> None:
            order.append("second")

        reg = HookRegistry()
        reg.on_session_idle(cb_first)
        reg.on_session_idle(cb_second)
        dispatcher = DefaultHookDispatcher(reg)
        await dispatcher.dispatch_session_event("session.idle", {})
        assert order == ["first", "second"]

    async def test_raising_callback_logged_and_subsequent_cb_still_runs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """REQ-RCA-031: raising callback is logged; dispatch continues (fail-open)."""
        after_raise: list[bool] = []

        async def exploding_cb(**kwargs: Any) -> None:
            raise RuntimeError("session hook exploded")

        async def good_cb(**kwargs: Any) -> None:
            after_raise.append(True)

        reg = HookRegistry()
        reg.on_session_idle(exploding_cb)
        reg.on_session_idle(good_cb)
        dispatcher = DefaultHookDispatcher(reg)

        with caplog.at_level(logging.WARNING):
            await dispatcher.dispatch_session_event("session.idle", {})

        assert after_raise == [True], "Good callback must still run after raising one"
        assert "session hook exploded" in caplog.text

    async def test_isp_hook_dispatcher_has_exactly_five_methods(self) -> None:
        """ISP: HookDispatcher Protocol has exactly 5 public methods after adding
        dispatch_session_event (4 tool-level + 1 generic session event)."""
        from swarmline.hooks.dispatcher import HookDispatcher

        public_methods = [
            m
            for m in dir(HookDispatcher)
            if not m.startswith("_") and callable(getattr(HookDispatcher, m, None))
        ]
        assert len(public_methods) == 5


# ===========================================================================
# 3. Lifecycle: file.edited — fired in react_strategy after edit-family tools
# ===========================================================================


class TestFileEditedLifecycle:
    """file.edited fires after edit/write/multi_edit/multi_file_edit tool completes."""

    async def test_file_edited_fires_with_tool_name_after_edit_tool(self) -> None:
        fired: list[dict[str, Any]] = []

        async def cb(event: str, **kwargs: Any) -> None:
            fired.append({"event": event, **kwargs})

        reg = HookRegistry()
        reg.on_file_edited(cb)
        llm = _MockLLM(
            [
                _tool_call("edit", {"path": "/src/a.py"}),
                _final("done"),
            ]
        )
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"edit": _noop_tool},
            hook_registry=reg,
        )
        await _collect(runtime, tools=[_EDIT_TOOL], mode_hint="react")

        assert len(fired) == 1
        assert fired[0]["event"] == "file.edited"
        assert fired[0].get("tool") == "edit"

    async def test_file_edited_fires_after_write_tool(self) -> None:
        fired: list[str] = []

        async def cb(event: str, **kwargs: Any) -> None:
            fired.append(event)

        reg = HookRegistry()
        reg.on_file_edited(cb)
        llm = _MockLLM(
            [
                _tool_call("write", {"path": "/src/b.py"}),
                _final("done"),
            ]
        )
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"write": _noop_tool},
            hook_registry=reg,
        )
        await _collect(runtime, tools=[_WRITE_TOOL], mode_hint="react")
        assert "file.edited" in fired

    async def test_file_edited_does_not_fire_for_non_edit_tool(self) -> None:
        fired: list[str] = []

        async def cb(event: str, **kwargs: Any) -> None:
            fired.append(event)

        reg = HookRegistry()
        reg.on_file_edited(cb)
        llm = _MockLLM(
            [
                _tool_call("echo", {"msg": "hello"}),
                _final("done"),
            ]
        )
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"echo": _noop_tool},
            hook_registry=reg,
        )
        await _collect(runtime, tools=[_ECHO_TOOL], mode_hint="react")
        assert fired == [], "file.edited must NOT fire for non-edit tools"

    async def test_file_edited_no_hooks_registered_run_completes_normally(self) -> None:
        """No file.edited hooks → no-op, existing run behaviour unchanged."""
        reg = HookRegistry()
        llm = _MockLLM(
            [
                _tool_call("edit", {"path": "/src/a.py"}),
                _final("ok"),
            ]
        )
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"edit": _noop_tool},
            hook_registry=reg,
        )
        events = await _collect(runtime, tools=[_EDIT_TOOL], mode_hint="react")
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1


# ===========================================================================
# 4. Lifecycle: session.idle — fired in ThinRuntime after run loop completes
# ===========================================================================


class TestSessionIdleLifecycle:
    """session.idle fires at end-of-turn (after run loop, after Stop hook)."""

    async def test_session_idle_fires_after_conversational_turn_completes(
        self,
    ) -> None:
        fired: list[str] = []

        async def cb(event: str, **kwargs: Any) -> None:
            fired.append(event)

        reg = HookRegistry()
        reg.on_session_idle(cb)
        llm = _MockLLM([_final("hello")])
        runtime = ThinRuntime(llm_call=llm, hook_registry=reg)
        await _collect(runtime)
        assert "session.idle" in fired

    async def test_session_idle_fires_after_react_turn_completes(self) -> None:
        fired: list[str] = []

        async def cb(event: str, **kwargs: Any) -> None:
            fired.append(event)

        reg = HookRegistry()
        reg.on_session_idle(cb)
        llm = _MockLLM(
            [
                _tool_call("edit", {"path": "/f.py"}),
                _final("done"),
            ]
        )
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"edit": _noop_tool},
            hook_registry=reg,
        )
        await _collect(runtime, tools=[_EDIT_TOOL], mode_hint="react")
        assert "session.idle" in fired

    async def test_session_idle_fires_after_stop_hook(self) -> None:
        """session.idle fires AFTER the Stop hook (ordering guarantee)."""
        order: list[str] = []

        async def stop_cb(**kwargs: Any) -> None:
            order.append("stop")

        async def idle_cb(event: str, **kwargs: Any) -> None:
            order.append("idle")

        reg = HookRegistry()
        reg.on_stop(stop_cb)
        reg.on_session_idle(idle_cb)
        llm = _MockLLM([_final("done")])
        runtime = ThinRuntime(llm_call=llm, hook_registry=reg)
        await _collect(runtime)
        assert order == ["stop", "idle"], f"Expected stop before idle, got {order}"

    async def test_session_idle_no_hooks_registered_noop(self) -> None:
        reg = HookRegistry()
        llm = _MockLLM([_final("hi")])
        runtime = ThinRuntime(llm_call=llm, hook_registry=reg)
        events = await _collect(runtime)
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1


# ===========================================================================
# 5. Lifecycle: session.compacted — fired after compaction filter in ThinRuntime
# ===========================================================================


class TestSessionCompactedLifecycle:
    """session.compacted fires after ConversationCompactionFilter.filter() runs."""

    async def test_session_compacted_fires_when_compaction_config_present(
        self,
    ) -> None:
        fired: list[str] = []

        async def cb(event: str, **kwargs: Any) -> None:
            fired.append(event)

        reg = HookRegistry()
        reg.on_session_compacted(cb)
        llm = _MockLLM([_final("compacted")])
        config = RuntimeConfig(
            runtime_name="thin",
            compaction=CompactionConfig(),
        )
        runtime = ThinRuntime(llm_call=llm, config=config, hook_registry=reg)
        await _collect(runtime)
        assert "session.compacted" in fired

    async def test_session_compacted_not_fired_without_compaction_config(
        self,
    ) -> None:
        fired: list[str] = []

        async def cb(event: str, **kwargs: Any) -> None:
            fired.append(event)

        reg = HookRegistry()
        reg.on_session_compacted(cb)
        llm = _MockLLM([_final("no compact")])
        # No compaction: RuntimeConfig default (compaction=None)
        runtime = ThinRuntime(llm_call=llm, hook_registry=reg)
        await _collect(runtime)
        assert "session.compacted" not in fired


# ===========================================================================
# 6. Fail-open through ThinRuntime (REQ-RCA-031 end-to-end)
# ===========================================================================


class TestSessionHookFailOpenRuntime:
    """Raising session hook callback is logged; run continues and yields final event."""

    async def test_raising_file_edited_run_still_yields_final_event(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def exploding(**kwargs: Any) -> None:
            raise RuntimeError("edit hook crashed")

        reg = HookRegistry()
        reg.on_file_edited(exploding)
        llm = _MockLLM(
            [
                _tool_call("edit", {"path": "/src/x.py"}),
                _final("still done"),
            ]
        )
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"edit": _noop_tool},
            hook_registry=reg,
        )
        with caplog.at_level(logging.WARNING):
            events = await _collect(runtime, tools=[_EDIT_TOOL], mode_hint="react")

        finals = [e for e in events if e.is_final]
        assert len(finals) == 1, "Run must complete even when session hook raises"
        assert "edit hook crashed" in caplog.text

    async def test_raising_session_idle_run_still_yields_final_event(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def exploding(event: str, **kwargs: Any) -> None:
            raise RuntimeError("idle hook crashed")

        reg = HookRegistry()
        reg.on_session_idle(exploding)
        llm = _MockLLM([_final("done")])
        runtime = ThinRuntime(llm_call=llm, hook_registry=reg)

        with caplog.at_level(logging.WARNING):
            events = await _collect(runtime)

        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert "idle hook crashed" in caplog.text

    async def test_raising_session_compacted_run_still_yields_final_event(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def exploding(event: str, **kwargs: Any) -> None:
            raise RuntimeError("compacted hook crashed")

        reg = HookRegistry()
        reg.on_session_compacted(exploding)
        llm = _MockLLM([_final("done")])
        config = RuntimeConfig(runtime_name="thin", compaction=CompactionConfig())
        runtime = ThinRuntime(llm_call=llm, config=config, hook_registry=reg)

        with caplog.at_level(logging.WARNING):
            events = await _collect(runtime)

        finals = [e for e in events if e.is_final]
        assert len(finals) == 1, "Run must complete even when session hook raises"
        assert "compacted hook crashed" in caplog.text


# ===========================================================================
# 7. F1 — file.edited on the NATIVE tool-calling path (REQ-RCA-030)
# ===========================================================================


class TestFileEditedNativePath:
    """file.edited fires when edit tools complete via native tool-calling path."""

    async def test_file_edited_fires_for_edit_tool_on_native_path(self) -> None:
        import time

        from swarmline.hooks.dispatcher import DefaultHookDispatcher
        from swarmline.runtime.thin.executor import ToolExecutor
        from swarmline.runtime.thin.native_tools import (
            NativeToolCall,
            NativeToolCallResult,
        )
        from swarmline.runtime.thin.react_strategy import run_react

        fired: list[dict[str, Any]] = []

        async def cb(event: str, **kwargs: Any) -> None:
            fired.append({"event": event, **kwargs})

        reg = HookRegistry()
        reg.on_file_edited(cb)
        dispatcher = DefaultHookDispatcher(reg)

        class _MockNative:
            _idx = 0
            _responses = [
                NativeToolCallResult(
                    text="editing",
                    tool_calls=(
                        NativeToolCall(
                            id="n1", name="edit", args={"path": "/src/f.py"}
                        ),
                    ),
                    stop_reason="tool_use",
                ),
                NativeToolCallResult(
                    text="done", tool_calls=(), stop_reason="end_turn"
                ),
            ]

            async def call_with_tools(
                self, messages: Any, system_prompt: Any, tools: Any, **kw: Any
            ) -> Any:
                r = self._responses[self._idx]
                self._idx += 1
                return r

        adapter = _MockNative()
        config = RuntimeConfig(runtime_name="thin", use_native_tools=True)
        executor = ToolExecutor(local_tools={"edit": _noop_tool})

        async def _fake_llm(msgs: Any, prompt: Any, **kw: Any) -> str:
            return _final("fallback")

        async for _ in run_react(
            _fake_llm,
            executor,
            [Message(role="user", content="edit")],
            "system",
            [_EDIT_TOOL],
            config,
            time.monotonic(),
            native_adapter=adapter,
            session_dispatcher=dispatcher,
        ):
            pass

        assert any(f["event"] == "file.edited" for f in fired), (
            "file.edited must fire on native tool-calling path"
        )
        assert any(f.get("tool") == "edit" for f in fired)

    async def test_file_edited_fires_for_multi_edit_on_native_path(self) -> None:
        import time

        from swarmline.hooks.dispatcher import DefaultHookDispatcher
        from swarmline.runtime.thin.executor import ToolExecutor
        from swarmline.runtime.thin.native_tools import (
            NativeToolCall,
            NativeToolCallResult,
        )
        from swarmline.runtime.thin.react_strategy import run_react

        fired: list[str] = []

        async def cb(event: str, **kwargs: Any) -> None:
            fired.append(event)

        reg = HookRegistry()
        reg.on_file_edited(cb)
        dispatcher = DefaultHookDispatcher(reg)

        class _MockNative:
            _idx = 0
            _responses = [
                NativeToolCallResult(
                    text="",
                    tool_calls=(
                        NativeToolCall(
                            id="n1", name="multi_edit", args={"path": "/a.py"}
                        ),
                    ),
                    stop_reason="tool_use",
                ),
                NativeToolCallResult(
                    text="done", tool_calls=(), stop_reason="end_turn"
                ),
            ]

            async def call_with_tools(
                self, messages: Any, system_prompt: Any, tools: Any, **kw: Any
            ) -> Any:
                r = self._responses[self._idx]
                self._idx += 1
                return r

        multi_edit_tool = ToolSpec(
            name="multi_edit",
            description="Multi edit",
            parameters={"type": "object", "properties": {}},
        )
        config = RuntimeConfig(runtime_name="thin", use_native_tools=True)
        executor = ToolExecutor(local_tools={"multi_edit": _noop_tool})

        async def _fake_llm(msgs: Any, prompt: Any, **kw: Any) -> str:
            return _final("fallback")

        async for _ in run_react(
            _fake_llm,
            executor,
            [Message(role="user", content="edit")],
            "system",
            [multi_edit_tool],
            config,
            time.monotonic(),
            native_adapter=_MockNative(),
            session_dispatcher=dispatcher,
        ):
            pass

        assert "file.edited" in fired

    async def test_no_file_edited_for_non_edit_tool_on_native_path(self) -> None:
        import time

        from swarmline.hooks.dispatcher import DefaultHookDispatcher
        from swarmline.runtime.thin.executor import ToolExecutor
        from swarmline.runtime.thin.native_tools import (
            NativeToolCall,
            NativeToolCallResult,
        )
        from swarmline.runtime.thin.react_strategy import run_react

        fired: list[str] = []

        async def cb(event: str, **kwargs: Any) -> None:
            fired.append(event)

        reg = HookRegistry()
        reg.on_file_edited(cb)
        dispatcher = DefaultHookDispatcher(reg)

        class _MockNative:
            _idx = 0
            _responses = [
                NativeToolCallResult(
                    text="",
                    tool_calls=(
                        NativeToolCall(id="n1", name="echo", args={"msg": "hi"}),
                    ),
                    stop_reason="tool_use",
                ),
                NativeToolCallResult(
                    text="done", tool_calls=(), stop_reason="end_turn"
                ),
            ]

            async def call_with_tools(
                self, messages: Any, system_prompt: Any, tools: Any, **kw: Any
            ) -> Any:
                r = self._responses[self._idx]
                self._idx += 1
                return r

        config = RuntimeConfig(runtime_name="thin", use_native_tools=True)
        executor = ToolExecutor(local_tools={"echo": _noop_tool})

        async def _fake_llm(msgs: Any, prompt: Any, **kw: Any) -> str:
            return _final("fallback")

        async for _ in run_react(
            _fake_llm,
            executor,
            [Message(role="user", content="echo")],
            "system",
            [_ECHO_TOOL],
            config,
            time.monotonic(),
            native_adapter=_MockNative(),
            session_dispatcher=dispatcher,
        ):
            pass

        assert fired == [], (
            "file.edited must NOT fire for non-edit tools on native path"
        )


# ===========================================================================
# 8. F2 — file.edited in architect mode Phase 2 (REQ-RCA-030)
# ===========================================================================


class TestFileEditedArchitectPath:
    """file.edited fires when run_architect_strategy Phase-2 executes an edit tool."""

    async def test_file_edited_fires_in_architect_phase2(self) -> None:
        import time

        from swarmline.hooks.dispatcher import DefaultHookDispatcher
        from swarmline.runtime.thin.architect import run_architect_strategy
        from swarmline.runtime.thin.executor import ToolExecutor

        fired: list[dict[str, Any]] = []

        async def cb(event: str, **kwargs: Any) -> None:
            fired.append({"event": event, **kwargs})

        reg = HookRegistry()
        reg.on_file_edited(cb)
        dispatcher = DefaultHookDispatcher(reg)

        call_count = 0

        async def multi_call_llm(messages: Any, prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Phase 1: plain text plan (not JSON envelope)
                return "Implement by editing /src/f.py"
            if call_count == 2:
                # Phase 2 iteration 1: edit tool call
                return _tool_call("edit", {"path": "/src/f.py"})
            # Phase 2 iteration 2+: final
            return _final("edit done")

        executor = ToolExecutor(local_tools={"edit": _noop_tool})
        config = RuntimeConfig(runtime_name="thin")

        async for _ in run_architect_strategy(
            raw_llm_call=multi_call_llm,
            executor=executor,
            messages=[Message(role="user", content="edit f.py")],
            system_prompt="System",
            tools=[_EDIT_TOOL],
            base_config=config,
            start_time=time.monotonic(),
            main_model="test-model",
            editor_model="test-editor-model",
            session_dispatcher=dispatcher,
        ):
            pass

        assert any(f["event"] == "file.edited" for f in fired), (
            "file.edited must fire in architect Phase 2 when edit tool completes"
        )


# ===========================================================================
# 9. F3 — session.idle on command-intercept path (REQ-RCA-030)
# ===========================================================================


class TestSessionIdleCommandIntercept:
    """session.idle fires when a /command is intercepted and completes normally."""

    async def test_session_idle_fires_on_command_intercept(self) -> None:
        from swarmline.commands.registry import CommandRegistry

        idle_fired: list[str] = []

        async def idle_cb(event: str, **kwargs: Any) -> None:
            idle_fired.append(event)

        reg = HookRegistry()
        reg.on_session_idle(idle_cb)

        cmd_registry = CommandRegistry()

        async def help_handler(*args: Any, **kwargs: Any) -> str:
            return "help text"

        cmd_registry.add("help", handler=help_handler, description="Help")

        llm = _MockLLM([])
        runtime = ThinRuntime(
            llm_call=llm,
            hook_registry=reg,
            command_registry=cmd_registry,
        )
        events = await _collect(runtime, text="/help")

        finals = [e for e in events if e.is_final]
        assert len(finals) == 1, "Command intercept must yield a final event"
        assert "session.idle" in idle_fired, (
            "session.idle must fire after command-intercept end-of-turn"
        )

    async def test_session_idle_command_fires_after_stop_hook(self) -> None:
        from swarmline.commands.registry import CommandRegistry

        order: list[str] = []

        async def stop_cb(**kwargs: Any) -> None:
            order.append("stop")

        async def idle_cb(event: str, **kwargs: Any) -> None:
            order.append("idle")

        reg = HookRegistry()
        reg.on_stop(stop_cb)
        reg.on_session_idle(idle_cb)

        cmd_registry = CommandRegistry()

        async def help_handler(*args: Any, **kwargs: Any) -> str:
            return "help text"

        cmd_registry.add("help", handler=help_handler, description="Help")

        llm = _MockLLM([])
        runtime = ThinRuntime(
            llm_call=llm,
            hook_registry=reg,
            command_registry=cmd_registry,
        )
        await _collect(runtime, text="/help")
        assert order == ["stop", "idle"], (
            f"Expected stop before idle on command path, got {order}"
        )


# ===========================================================================
# 10. F2 additional coverage: multi_file_edit, None-dispatcher, idle-on-error
# ===========================================================================


class TestMultiFileEditNameCoverage:
    """multi_file_edit tool name is in _EDIT_TOOL_NAMES and dispatches file.edited."""

    async def test_multi_file_edit_dispatches_file_edited_on_text_path(self) -> None:
        """multi_file_edit in the text-ReAct path triggers file.edited (via _maybe_dispatch)."""
        fired: list[str] = []

        async def cb(event: str, **kwargs: Any) -> None:
            fired.append(event)

        reg = HookRegistry()
        reg.on_file_edited(cb)

        multi_file_edit_tool = ToolSpec(
            name="multi_file_edit",
            description="Edit multiple files",
            parameters={"type": "object", "properties": {}},
        )
        llm = _MockLLM(
            [
                _tool_call("multi_file_edit", {"file_path": "/a.py"}),
                _final("done"),
            ]
        )
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"multi_file_edit": _noop_tool},
            hook_registry=reg,
        )
        await _collect(runtime, tools=[multi_file_edit_tool], mode_hint="react")
        assert "file.edited" in fired, (
            "multi_file_edit must trigger file.edited via _EDIT_TOOL_NAMES gate"
        )


class TestNoneDispatcherNoOp:
    """hook_registry=None means _hook_dispatcher is None — byte-identical no-op."""

    async def test_none_hook_registry_run_completes_without_dispatch(self) -> None:
        """ThinRuntime with no hook_registry at all — true None path, not empty registry."""
        llm = _MockLLM([_final("hello")])
        # Intentionally NO hook_registry kwarg; defaults to None
        runtime = ThinRuntime(llm_call=llm)
        events = await _collect(runtime)
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1, "Run must complete normally with hook_registry=None"

    async def test_none_hook_registry_edit_tool_completes_without_dispatch(
        self,
    ) -> None:
        """file.edited no-op when session_dispatcher is None (not just empty registry)."""
        llm = _MockLLM(
            [
                _tool_call("edit", {"path": "/f.py"}),
                _final("done"),
            ]
        )
        # No hook_registry — session_dispatcher is None → _maybe_dispatch_file_edited no-ops
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"edit": _noop_tool},
        )
        events = await _collect(runtime, tools=[_EDIT_TOOL], mode_hint="react")
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1


class TestSessionIdleErrorEventBehavior:
    """session.idle fires only on normal (non-error) end-of-turn."""

    async def test_session_idle_does_not_fire_on_error_event_turn(self) -> None:
        """When the strategy yields a terminal error event, session.idle is suppressed."""
        idle_fired: list[str] = []

        async def idle_cb(event: str, **kwargs: Any) -> None:
            idle_fired.append(event)

        reg = HookRegistry()
        reg.on_session_idle(idle_cb)

        # max_tool_calls=0 → strategy yields RuntimeEvent.error immediately on
        # first tool_call and returns (no Final event, no exception raised).
        config = RuntimeConfig(runtime_name="thin", max_tool_calls=0)
        llm = _MockLLM([_tool_call("edit", {"path": "/f.py"})])
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"edit": _noop_tool},
            hook_registry=reg,
            config=config,
        )
        events = await _collect(runtime, tools=[_EDIT_TOOL], mode_hint="react")
        error_events = [e for e in events if e.is_error]
        assert len(error_events) >= 1, (
            "Precondition: error event must have been yielded"
        )
        assert "session.idle" not in idle_fired, (
            "session.idle must NOT fire when the turn ends with a terminal error event"
        )

    async def test_session_idle_fires_on_clean_turn(self) -> None:
        """Baseline: session.idle DOES fire on a normal (non-error) turn."""
        idle_fired: list[str] = []

        async def idle_cb(event: str, **kwargs: Any) -> None:
            idle_fired.append(event)

        reg = HookRegistry()
        reg.on_session_idle(idle_cb)
        llm = _MockLLM([_final("ok")])
        runtime = ThinRuntime(llm_call=llm, hook_registry=reg)
        events = await _collect(runtime)
        finals = [e for e in events if e.is_final]
        assert len(finals) == 1
        assert "session.idle" in idle_fired, (
            "session.idle MUST fire on a normal (non-error) end-of-turn"
        )
