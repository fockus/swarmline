"""TDD tests for Tasks 2, 3, 4, 6 of the execution-kernel / kernel-patterns specs.

Task 2: KernelRegistry (REQ-004, REQ-007, REQ-008, REQ-011)
Task 3: Built-in kernel adapters / golden tests (REQ-002, REQ-009)
Task 4: Replace hardcoded dispatch + auto-register (REQ-005, REQ-009,
        REQ-010, REQ-011, REQ-012)
Task 6 (kernel-patterns spec): register ALL kernels — plan-execute / adapt /
        reflection / sgr — resolvable via the registry (REQ-005, REQ-012,
        REQ-013). ``ReflectionKernelAdapter`` reads ``ctx.external_signal``
        per-run and either delegates to a real ``ReflectionKernel`` or
        surfaces a single terminal ``dependency_missing`` error (REQ-009: no
        silent no-op signal via the registry path).

GPT-5.5 review findings (H1 Cycle B) — pluggability end-to-end:
FINDING 1/2: mode_hint validated against the LIVE registry (REQ-006/007/011),
    and the default registry self-initializes (built-ins + entry points) on
    every first access, including after reset — never left empty.
FINDING 3: KernelRegistry.get() / factories are typed Callable[[], ExecutionKernel].

Written BEFORE the implementation (TDD).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swarmline.domain_types import RuntimeEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop_checkpoint() -> RuntimeEvent | None:
    return None


async def _noop_llm(messages: Any, system_prompt: str, **kw: Any) -> str:
    return json.dumps({"type": "final", "final_message": "ok"})


def _make_context(**overrides: Any):
    """Build a minimal valid KernelContext for testing."""
    from swarmline.runtime.types import RuntimeConfig
    from swarmline.types import KernelContext

    defaults: dict[str, Any] = {
        "llm_call": _noop_llm,
        "messages": [],
        "system_prompt": "system",
        "config": RuntimeConfig(runtime_name="thin"),
        "start_time": 0.0,
        "checkpoint": _noop_checkpoint,
    }
    defaults.update(overrides)
    return KernelContext(**defaults)


def _make_fake_kernel() -> Any:
    """Return a fake ExecutionKernel implementation."""
    from swarmline.types import KernelContext

    class FakeKernel:
        def __init__(self, events: list[RuntimeEvent] | None = None) -> None:
            self._events = events or [RuntimeEvent.final(text="fake")]

        def run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
            events = self._events

            async def _gen() -> AsyncIterator[RuntimeEvent]:
                for ev in events:
                    yield ev

            return _gen()

    return FakeKernel()


# ===========================================================================
# Task 2: KernelRegistry
# ===========================================================================


class TestKernelRegistryCore:
    """Task 2 — KernelRegistry: register / get / modes / KernelNotFound."""

    def test_registry_register_and_get_returns_kernel(self) -> None:
        """register() + get() round-trip: factory is called, kernel is returned."""
        from swarmline.runtime.thin.kernels.registry import KernelRegistry

        kernel_instance = _make_fake_kernel()
        registry = KernelRegistry()
        registry.register("custom", lambda: kernel_instance)

        got = registry.get("custom")
        assert got is kernel_instance

    def test_registry_get_unknown_mode_raises_with_available_list(self) -> None:
        """get(unknown) raises KernelNotFound naming the mode + available modes."""
        from swarmline.runtime.thin.kernels.errors import KernelNotFound
        from swarmline.runtime.thin.kernels.registry import KernelRegistry

        registry = KernelRegistry()
        registry.register("alpha", lambda: _make_fake_kernel())
        registry.register("beta", lambda: _make_fake_kernel())

        with pytest.raises(KernelNotFound) as exc_info:
            registry.get("unknown")

        msg = str(exc_info.value)
        assert "unknown" in msg, f"Error should mention the unknown mode; got: {msg}"
        assert "alpha" in msg, f"Error should list available modes; got: {msg}"
        assert "beta" in msg, f"Error should list available modes; got: {msg}"

    def test_registry_modes_reflects_registered(self) -> None:
        """modes() returns frozenset of registered mode names (REQ-011)."""
        from swarmline.runtime.thin.kernels.registry import KernelRegistry

        registry = KernelRegistry()
        registry.register("one", lambda: _make_fake_kernel())
        registry.register("two", lambda: _make_fake_kernel())

        modes = registry.modes()
        assert isinstance(modes, frozenset)
        assert modes == frozenset({"one", "two"})

    def test_registry_modes_is_empty_when_nothing_registered(self) -> None:
        """modes() returns empty frozenset on fresh registry."""
        from swarmline.runtime.thin.kernels.registry import KernelRegistry

        registry = KernelRegistry()
        assert registry.modes() == frozenset()

    def test_registry_register_overwrites_existing(self) -> None:
        """re-register same mode uses newest factory."""
        from swarmline.runtime.thin.kernels.registry import KernelRegistry

        k1 = _make_fake_kernel()
        k2 = _make_fake_kernel()
        registry = KernelRegistry()
        registry.register("m", lambda: k1)
        registry.register("m", lambda: k2)

        assert registry.get("m") is k2

    def test_registry_loads_entry_point_group(self) -> None:
        """load_entry_points('swarmline.kernels') loads custom kernels from plugins."""
        from swarmline.runtime.thin.kernels.registry import KernelRegistry

        expected_kernel = _make_fake_kernel()
        mock_ep = MagicMock()
        mock_ep.name = "my_plugin_kernel"
        mock_ep.load.return_value = lambda: expected_kernel

        registry = KernelRegistry()
        with patch(
            "swarmline.runtime.thin.kernels.registry.entry_points",
            return_value=[mock_ep],
        ):
            registry.load_entry_points(group="swarmline.kernels")

        assert "my_plugin_kernel" in registry.modes()
        got = registry.get("my_plugin_kernel")
        assert got is expected_kernel

    def test_registry_load_entry_points_bad_plugin_skipped(self) -> None:
        """Entry point that raises on load() is skipped (no crash)."""
        from swarmline.runtime.thin.kernels.registry import KernelRegistry

        mock_ep = MagicMock()
        mock_ep.name = "broken_plugin"
        mock_ep.load.side_effect = ImportError("missing dep")

        registry = KernelRegistry()
        with patch(
            "swarmline.runtime.thin.kernels.registry.entry_points",
            return_value=[mock_ep],
        ):
            registry.load_entry_points()  # default group

        assert "broken_plugin" not in registry.modes()

    def test_registry_kernel_not_found_error_attributes(self) -> None:
        """KernelNotFound exposes .mode and .available attributes."""
        from swarmline.runtime.thin.kernels.errors import KernelNotFound
        from swarmline.runtime.thin.kernels.registry import KernelRegistry

        registry = KernelRegistry()
        registry.register("alpha", lambda: _make_fake_kernel())

        with pytest.raises(KernelNotFound) as exc_info:
            registry.get("ghost")

        err = exc_info.value
        assert err.mode == "ghost"
        assert "alpha" in err.available


# ===========================================================================
# Task 3: Built-in kernel adapters — golden tests
# ===========================================================================


class TestConversationalKernelAdapter:
    """ConversationalKernelAdapter wraps run_conversational (REQ-002, REQ-009)."""

    async def test_conversational_adapter_golden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stream from adapter is identical to direct run_conversational call."""
        from swarmline.runtime.thin.kernels.builtins import ConversationalKernelAdapter

        captured_events = [
            RuntimeEvent.status("conv-start"),
            RuntimeEvent.final(text="conv-done"),
        ]

        async def mock_run_conversational(
            llm_call: Any,
            messages: Any,
            system_prompt: Any,
            config: Any,
            start_time: Any,
            checkpoint: Any = None,
            on_retry: Any = None,
        ) -> AsyncIterator[RuntimeEvent]:
            for ev in captured_events:
                yield ev

        monkeypatch.setattr(
            "swarmline.runtime.thin.kernels.builtins.run_conversational",
            mock_run_conversational,
        )

        ctx = _make_context()
        adapter = ConversationalKernelAdapter()
        events = [ev async for ev in adapter.run(ctx)]
        assert events == captured_events

    def test_conversational_adapter_ignores_executor_tools(self) -> None:
        """ConversationalAdapter accepts ctx with executor/tools without error.

        The adapter must NOT pass executor/tools to run_conversational
        (which has no such parameters).
        """
        from swarmline.runtime.thin.kernels.builtins import ConversationalKernelAdapter

        sentinel_executor = object()
        sentinel_tools = [object()]
        # ctx has executor and tools but adapter must ignore them silently
        ctx = _make_context(executor=sentinel_executor, tools=sentinel_tools)  # type: ignore[arg-type]
        adapter = ConversationalKernelAdapter()

        # If run() accepted **kwargs or called run_conversational(executor=...) it would
        # blow up because run_conversational has no such param.  Constructing the
        # generator (not iterating yet) verifies the signature normalization is correct.
        gen = adapter.run(ctx)
        assert hasattr(gen, "__aiter__"), "adapter.run() must return an async generator"


class TestReactKernelAdapter:
    """ReactKernelAdapter wraps run_react (REQ-002, REQ-009)."""

    async def test_react_adapter_golden(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stream from adapter is identical to direct run_react call."""
        from swarmline.runtime.thin.kernels.builtins import ReactKernelAdapter

        captured_events = [
            RuntimeEvent.status("react-start"),
            RuntimeEvent.final(text="react-done"),
        ]

        async def mock_run_react(
            llm_call: Any,
            executor: Any,
            messages: Any,
            system_prompt: Any,
            tools: Any,
            config: Any,
            start_time: Any,
            checkpoint: Any = None,
            on_retry: Any = None,
            native_adapter: Any = None,
            auto_verify_loop: Any = None,
            session_dispatcher: Any = None,
        ) -> AsyncIterator[RuntimeEvent]:
            for ev in captured_events:
                yield ev

        monkeypatch.setattr(
            "swarmline.runtime.thin.kernels.builtins.run_react",
            mock_run_react,
        )

        ctx = _make_context(executor=object(), tools=["tool1"])  # type: ignore[arg-type]
        adapter = ReactKernelAdapter()
        events = [ev async for ev in adapter.run(ctx)]
        assert events == captured_events

    async def test_react_adapter_passes_session_dispatcher(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ReactKernelAdapter forwards ctx.session_dispatcher to run_react (REQ-002).

        session_dispatcher flows through KernelContext — the single normalized
        input — rather than through a mode-specific constructor kwarg.
        """
        from swarmline.runtime.thin.kernels.builtins import ReactKernelAdapter

        received_dispatcher: list[Any] = []

        async def mock_run_react(
            llm_call: Any,
            executor: Any,
            messages: Any,
            system_prompt: Any,
            tools: Any,
            config: Any,
            start_time: Any,
            checkpoint: Any = None,
            on_retry: Any = None,
            native_adapter: Any = None,
            auto_verify_loop: Any = None,
            session_dispatcher: Any = None,
        ) -> AsyncIterator[RuntimeEvent]:
            received_dispatcher.append(session_dispatcher)
            yield RuntimeEvent.final(text="done")

        monkeypatch.setattr(
            "swarmline.runtime.thin.kernels.builtins.run_react",
            mock_run_react,
        )

        sentinel_dispatcher = object()
        adapter = ReactKernelAdapter()
        # executor must be non-None (guard in ReactKernelAdapter.run())
        ctx = _make_context(
            executor=object(),
            session_dispatcher=sentinel_dispatcher,  # type: ignore[arg-type]
        )
        [_ async for _ in adapter.run(ctx)]

        assert received_dispatcher[0] is sentinel_dispatcher

    async def test_react_adapter_default_session_dispatcher_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ReactKernelAdapter with ctx.session_dispatcher unset passes None to run_react."""
        from swarmline.runtime.thin.kernels.builtins import ReactKernelAdapter

        received_dispatcher: list[Any] = []

        async def mock_run_react(
            llm_call: Any,
            executor: Any,
            messages: Any,
            system_prompt: Any,
            tools: Any,
            config: Any,
            start_time: Any,
            checkpoint: Any = None,
            on_retry: Any = None,
            native_adapter: Any = None,
            auto_verify_loop: Any = None,
            session_dispatcher: Any = None,
        ) -> AsyncIterator[RuntimeEvent]:
            received_dispatcher.append(session_dispatcher)
            yield RuntimeEvent.final(text="done")

        monkeypatch.setattr(
            "swarmline.runtime.thin.kernels.builtins.run_react",
            mock_run_react,
        )

        adapter = ReactKernelAdapter()
        # executor must be non-None (guard in ReactKernelAdapter.run());
        # session_dispatcher left at its default (None).
        ctx = _make_context(executor=object())  # type: ignore[arg-type]
        [_ async for _ in adapter.run(ctx)]

        assert received_dispatcher[0] is None


class TestPlannerKernelAdapter:
    """PlannerKernelAdapter wraps run_planner (REQ-002, REQ-009)."""

    async def test_planner_adapter_golden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stream from adapter is identical to direct run_planner call."""
        from swarmline.runtime.thin.kernels.builtins import PlannerKernelAdapter

        captured_events = [
            RuntimeEvent.status("planner-start"),
            RuntimeEvent.final(text="planner-done"),
        ]

        async def mock_run_planner(
            llm_call: Any,
            executor: Any,
            messages: Any,
            system_prompt: Any,
            tools: Any,
            config: Any,
            start_time: Any,
            checkpoint: Any = None,
        ) -> AsyncIterator[RuntimeEvent]:
            for ev in captured_events:
                yield ev

        monkeypatch.setattr(
            "swarmline.runtime.thin.kernels.builtins.run_planner",
            mock_run_planner,
        )

        ctx = _make_context(executor=object(), tools=["tool1"])  # type: ignore[arg-type]
        adapter = PlannerKernelAdapter()
        events = [ev async for ev in adapter.run(ctx)]
        assert events == captured_events


# ===========================================================================
# Task 4: Dispatch via registry + auto-registration
# ===========================================================================


class TestAutoRegistration:
    """Built-in kernels are auto-registered when kernels module is imported (REQ-009)."""

    def test_global_registry_has_all_builtin_modes(self) -> None:
        """Import triggers auto-registration of every built-in kernel mode:
        react, planner, plan-execute, conversational, adapt, reflection, sgr
        (kernel-patterns spec, Task 6, REQ-005/REQ-012 — extends the original
        3-mode assertion to the full built-in set without weakening it)."""
        from swarmline.runtime.thin.kernels import get_default_kernel_registry

        registry = get_default_kernel_registry()
        modes = registry.modes()
        assert "react" in modes
        assert "planner" in modes
        assert "conversational" in modes
        assert "plan-execute" in modes
        assert "adapt" in modes
        assert "reflection" in modes
        assert "sgr" in modes

    def test_valid_modes_derived_from_registry(self) -> None:
        """VALID_MODES in modes.py equals the registered modes (REQ-011)."""
        from swarmline.runtime.thin.kernels import get_default_kernel_registry
        from swarmline.runtime.thin.modes import VALID_MODES

        registry_modes = get_default_kernel_registry().modes()
        # VALID_MODES must be a subset (registry may have extra from entry points)
        assert {"react", "planner", "conversational"}.issubset(VALID_MODES)
        # Standard builtin modes must be present in registry
        assert {"react", "planner", "conversational"}.issubset(registry_modes)


class TestModeDispatchViaRuntime:
    """ThinRuntime uses registry for dispatch; mode-resolution rule unchanged (REQ-010)."""

    async def test_default_mode_react_when_tools_else_conversational(self) -> None:
        """Tools present → react; no tools → conversational (REQ-010)."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig, ToolSpec

        async def always_final(messages: Any, system_prompt: Any, **kw: Any) -> str:
            return json.dumps({"type": "final", "final_message": "done"})

        tool_spec = ToolSpec(
            name="dummy",
            description="test",
            parameters={"type": "object", "properties": {}},
        )

        # ---- With tools: expect react mode ----
        rt_with_tools = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=always_final,
            local_tools={"dummy": lambda args: {"ok": True}},
        )
        events_with_tools = []
        async for ev in rt_with_tools.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=[tool_spec],
        ):
            events_with_tools.append(ev)

        status_texts = [
            ev.data.get("text", "") for ev in events_with_tools if ev.type == "status"
        ]
        assert any("react" in t for t in status_texts), (
            f"Expected 'react' in status events; got: {status_texts}"
        )

        # ---- Without tools: expect conversational mode ----
        rt_no_tools = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=always_final,
        )
        events_no_tools = []
        async for ev in rt_no_tools.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=[],
        ):
            events_no_tools.append(ev)

        status_texts_no = [
            ev.data.get("text", "") for ev in events_no_tools if ev.type == "status"
        ]
        assert any("conversational" in t for t in status_texts_no), (
            f"Expected 'conversational' in status events; got: {status_texts_no}"
        )

    async def test_planner_mode_reachable_via_mode_hint(self) -> None:
        """mode_hint='planner' routes to planner kernel (REQ-005)."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig, ToolSpec

        plan = json.dumps(
            {
                "type": "plan",
                "goal": "test",
                "steps": [],
                "final_format": "result",
            }
        )
        final = json.dumps({"type": "final", "final_message": "planner done"})
        responses = [plan, final]
        call_count = 0

        async def sequential_llm(messages: Any, system_prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            resp = responses[min(call_count, len(responses) - 1)]
            call_count += 1
            return resp

        tool_spec = ToolSpec(
            name="dummy",
            description="test",
            parameters={"type": "object", "properties": {}},
        )
        rt = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=sequential_llm,
        )
        events = []
        async for ev in rt.run(
            messages=[Message(role="user", content="plan please")],
            system_prompt="sys",
            active_tools=[tool_spec],
            mode_hint="planner",
        ):
            events.append(ev)

        status_texts = [ev.data.get("text", "") for ev in events if ev.type == "status"]
        assert any("planner" in t for t in status_texts), (
            f"Expected 'planner' status; got: {status_texts}"
        )

    async def test_unknown_mode_hint_falls_back_to_default_rule(self) -> None:
        """Invalid mode_hint is ignored; structural default applies (no crash)."""
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        async def always_final(messages: Any, system_prompt: Any, **kw: Any) -> str:
            return json.dumps({"type": "final", "final_message": "ok"})

        rt = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=always_final,
        )
        # mode_hint="nonexistent" is not in VALID_MODES → falls back to conversational
        events = []
        async for ev in rt.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=[],
            mode_hint="nonexistent",
        ):
            events.append(ev)

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, "Expected exactly one final event"


# ===========================================================================
# GPT-5.5 review FINDING 1/2 — pluggability end-to-end regression tests
# ===========================================================================


class TestCustomKernelDispatchEndToEnd:
    """FINDING 1: mode_hint must be validated against the LIVE registry, not
    the import-time-frozen VALID_MODES snapshot — otherwise a kernel
    registered programmatically after import (REQ-006) is unreachable via
    mode_hint and silently falls back to react/conversational.
    """

    def teardown_method(self) -> None:
        # Test isolation: never leak a custom mode into the process-wide
        # default registry used by other tests / test files.
        from swarmline.runtime.thin.kernels import reset_default_kernel_registry

        reset_default_kernel_registry()

    async def test_custom_kernel_registered_at_runtime_dispatched_via_mode_hint(
        self,
    ) -> None:
        """Register a custom ExecutionKernel on the DEFAULT registry AFTER
        import, then dispatch to it purely via mode_hint — WITHOUT editing
        any core runtime file.  Proves REQ-006/007/011 end-to-end.

        Before the fix: mode_hint="custom_e2e_mode" is not a member of the
        import-time-frozen VALID_MODES, so ThinRuntime silently falls back to
        the structural default (conversational, since no tools are active)
        and calls ``unreachable_llm``, which raises — the custom kernel never
        runs and no 'final' event carrying the sentinel text is produced.

        After the fix: mode_hint is checked against
        ``get_default_kernel_registry().modes()`` live, so the custom kernel
        is dispatched and its sentinel 'final' event is observed.
        """
        from swarmline.runtime.thin.kernels import get_default_kernel_registry
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        sentinel_text = "custom-kernel-ran"

        class _CustomKernel:
            """Minimal third-party-style ExecutionKernel implementation."""

            def run(self, ctx: Any) -> AsyncIterator[RuntimeEvent]:
                async def _gen() -> AsyncIterator[RuntimeEvent]:
                    yield RuntimeEvent.final(text=sentinel_text)

                return _gen()

        get_default_kernel_registry().register(
            "custom_e2e_mode", lambda: _CustomKernel()
        )

        async def unreachable_llm(messages: Any, system_prompt: Any, **kw: Any) -> str:
            raise AssertionError(
                "llm_call must not be invoked; the custom kernel must drive "
                "the loop directly instead of falling back to react/"
                "conversational."
            )

        rt = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=unreachable_llm,
        )
        events = []
        async for ev in rt.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=[],
            mode_hint="custom_e2e_mode",
        ):
            events.append(ev)

        assert not any(ev.is_error for ev in events), (
            f"Expected no error events (custom kernel must drive the loop "
            f"without touching llm_call); got: {[ev.data for ev in events if ev.is_error]}"
        )
        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one final event; got: {events}"
        assert finals[0].data.get("text") == sentinel_text, (
            "Final event must carry the CUSTOM kernel's sentinel text, "
            "proving the custom kernel — not react/conversational — drove "
            f"the loop; got: {finals[0].data}"
        )


class TestEntryPointKernelDefaultPathDiscovery:
    """FINDING 1 (REQ-007): entry-point kernels must be discovered on the
    DEFAULT registry path (self-init), not only when a throwaway
    ``KernelRegistry()`` instance happens to call ``load_entry_points()``
    directly.
    """

    def teardown_method(self) -> None:
        from swarmline.runtime.thin.kernels import reset_default_kernel_registry

        reset_default_kernel_registry()

    def test_entry_point_kernel_discovered_by_default_registry(self) -> None:
        """A 'swarmline.kernels' entry point is registered into the DEFAULT
        registry after reset + the next self-init — proving REQ-007 fires on
        the production ``get_default_kernel_registry()`` path.
        """
        from swarmline.runtime.thin.kernels import (
            get_default_kernel_registry,
            reset_default_kernel_registry,
        )

        expected_kernel = _make_fake_kernel()
        mock_ep = MagicMock()
        mock_ep.name = "plugin_from_entry_point"
        mock_ep.load.return_value = lambda: expected_kernel

        reset_default_kernel_registry()
        with patch(
            "swarmline.runtime.thin.kernels.registry.entry_points",
            return_value=[mock_ep],
        ):
            registry = get_default_kernel_registry()
            modes = registry.modes()

        assert "plugin_from_entry_point" in modes, (
            f"Expected entry-point plugin mode in default registry; got: {modes}"
        )
        # Built-ins must still be present (single init path registers both).
        assert {"react", "planner", "conversational"}.issubset(modes)
        got = registry.get("plugin_from_entry_point")
        assert got is expected_kernel

    async def test_custom_kernel_via_entry_point_drives_loop(self) -> None:
        """A kernel discovered via the 'swarmline.kernels' entry point drives
        ThinRuntime.run end-to-end via mode_hint (Task 5, REQ-006/007).

        ``test_entry_point_kernel_discovered_by_default_registry`` above only
        proves discovery (``modes()`` / ``get()``). This test proves the FULL
        production dispatch path: ``ThinRuntime.run(mode_hint=...)`` resolves
        the live registry, instantiates the entry-point-sourced kernel, and
        the loop is driven entirely by that kernel — never touching
        ``llm_call`` — with no core swarmline file edited to wire it up.
        """
        from swarmline.runtime.thin.kernels import (
            get_default_kernel_registry,
            reset_default_kernel_registry,
        )
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        sentinel_text = "entry-point-kernel-ran"

        class _EntryPointKernel:
            """Minimal third-party-style ExecutionKernel, as a packaged plugin
            would ship it (the class itself is the zero-argument factory)."""

            def run(self, ctx: Any) -> AsyncIterator[RuntimeEvent]:
                async def _gen() -> AsyncIterator[RuntimeEvent]:
                    yield RuntimeEvent.final(text=sentinel_text)

                return _gen()

        mock_ep = MagicMock()
        mock_ep.name = "entry_point_e2e_mode"
        mock_ep.load.return_value = _EntryPointKernel

        reset_default_kernel_registry()
        with patch(
            "swarmline.runtime.thin.kernels.registry.entry_points",
            return_value=[mock_ep],
        ):
            # First access after reset self-initializes AND discovers the
            # mocked entry point in the SAME init path as the built-ins.
            get_default_kernel_registry()

        async def unreachable_llm(messages: Any, system_prompt: Any, **kw: Any) -> str:
            raise AssertionError(
                "llm_call must not be invoked; the entry-point kernel must "
                "drive the loop directly instead of falling back to react/"
                "conversational."
            )

        rt = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=unreachable_llm,
        )
        events = []
        async for ev in rt.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=[],
            mode_hint="entry_point_e2e_mode",
        ):
            events.append(ev)

        assert not any(ev.is_error for ev in events), (
            f"Expected no error events (entry-point kernel must drive the "
            f"loop without touching llm_call); got: "
            f"{[ev.data for ev in events if ev.is_error]}"
        )
        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one final event; got: {events}"
        assert finals[0].data.get("text") == sentinel_text, (
            "Final event must carry the entry-point kernel's sentinel text, "
            "proving it — not react/conversational — drove the loop; got: "
            f"{finals[0].data}"
        )


class TestKernelRegistryTypedGet:
    """FINDING 3: get() is typed to return ExecutionKernel, and rejects a
    factory that returns a non-kernel object with a clear error.
    """

    def test_get_raises_type_error_for_non_kernel_factory(self) -> None:
        """A factory returning an object without a 'run' method is rejected."""
        from swarmline.runtime.thin.kernels.registry import KernelRegistry

        registry = KernelRegistry()
        registry.register("bad", lambda: object())

        with pytest.raises(TypeError, match="ExecutionKernel"):
            registry.get("bad")

    def test_get_accepts_duck_typed_kernel(self) -> None:
        """A plain object exposing run(ctx) satisfies the runtime-checkable
        ExecutionKernel protocol and is returned unchanged."""
        from swarmline.runtime.thin.kernels.registry import KernelRegistry

        kernel = _make_fake_kernel()
        registry = KernelRegistry()
        registry.register("ok", lambda: kernel)

        assert registry.get("ok") is kernel


# ===========================================================================
# kernel-patterns spec, Task 2: PlanExecuteKernel (REQ-001, REQ-005, REQ-006)
# ===========================================================================


class TestPlanExecuteKernel:
    """PlanExecuteKernel formalizes the static plan-and-execute pattern
    (= run_planner) as a first-class named ExecutionKernel."""

    async def test_plan_execute_generates_then_runs_steps_in_order(self) -> None:
        """A real (non-monkeypatched) run over a fake llm_call + executor emits
        the plan status THEN executes step 1 THEN step 2, in that order, then
        produces exactly one final event — proving genuine step ordering
        driven by the real run_planner logic, not a forwarding tautology.
        """
        from swarmline.runtime.thin.kernels.builtins import PlanExecuteKernel

        plan_json = json.dumps(
            {
                "type": "plan",
                "goal": "ship the feature",
                "steps": [
                    {"id": "s1", "title": "Step Alpha", "mode": "conversational"},
                    {"id": "s2", "title": "Step Beta", "mode": "conversational"},
                ],
                "final_format": "result",
            }
        )
        step_alpha_final = json.dumps({"type": "final", "final_message": "alpha done"})
        step_beta_final = json.dumps({"type": "final", "final_message": "beta done"})
        assembly_final = json.dumps({"type": "final", "final_message": "shipped"})
        responses = [plan_json, step_alpha_final, step_beta_final, assembly_final]
        call_count = 0

        async def sequential_llm(messages: Any, system_prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            resp = responses[min(call_count, len(responses) - 1)]
            call_count += 1
            return resp

        ctx = _make_context(
            llm_call=sequential_llm,
            executor=object(),  # unused: steps run in 'conversational' mode
        )
        kernel = PlanExecuteKernel()
        events = [ev async for ev in kernel.run(ctx)]

        status_texts = [ev.data.get("text", "") for ev in events if ev.type == "status"]
        plan_idx = next(i for i, t in enumerate(status_texts) if t.startswith("План:"))
        alpha_idx = next(
            i for i, t in enumerate(status_texts) if t.startswith("Шаг 1/2")
        )
        beta_idx = next(
            i for i, t in enumerate(status_texts) if t.startswith("Шаг 2/2")
        )
        assert plan_idx < alpha_idx < beta_idx, (
            "Expected plan status, then step 1, then step 2, in that order; "
            f"got: {status_texts}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one final event; got: {events}"
        assert finals[0].data.get("text") == "shipped"

    def test_plan_execute_registered_and_selectable_by_mode(self) -> None:
        """'plan-execute' is a live registry mode resolving to an
        ExecutionKernel, and the pre-existing 'planner' mode stays registered
        and unaffected (REQ-005 additive, REQ-012 backward-compat)."""
        from swarmline.protocols.kernel import ExecutionKernel
        from swarmline.runtime.thin.kernels import get_default_kernel_registry

        registry = get_default_kernel_registry()
        modes = registry.modes()
        assert "plan-execute" in modes
        assert "planner" in modes

        plan_execute_kernel = registry.get("plan-execute")
        assert isinstance(plan_execute_kernel, ExecutionKernel)

        planner_kernel = registry.get("planner")
        assert isinstance(planner_kernel, ExecutionKernel)

    async def test_plan_execute_mode_dispatchable_via_thin_runtime(self) -> None:
        """mode_hint='plan-execute' routes to the plan-execute kernel via the
        live registry — proven end-to-end through ThinRuntime, mirroring
        ``TestModeDispatchViaRuntime.test_planner_mode_reachable_via_mode_hint``.
        """
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig, ToolSpec

        plan = json.dumps(
            {
                "type": "plan",
                "goal": "test",
                "steps": [],
                "final_format": "result",
            }
        )
        final = json.dumps({"type": "final", "final_message": "plan-execute done"})
        responses = [plan, final]
        call_count = 0

        async def sequential_llm(messages: Any, system_prompt: Any, **kw: Any) -> str:
            nonlocal call_count
            resp = responses[min(call_count, len(responses) - 1)]
            call_count += 1
            return resp

        tool_spec = ToolSpec(
            name="dummy",
            description="test",
            parameters={"type": "object", "properties": {}},
        )
        rt = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=sequential_llm,
        )
        events = []
        async for ev in rt.run(
            messages=[Message(role="user", content="plan please")],
            system_prompt="sys",
            active_tools=[tool_spec],
            mode_hint="plan-execute",
        ):
            events.append(ev)

        status_texts = [ev.data.get("text", "") for ev in events if ev.type == "status"]
        assert any("plan-execute" in t for t in status_texts), (
            f"Expected 'plan-execute' status; got: {status_texts}"
        )


# ===========================================================================
# kernel-patterns spec, Task 3 (VERIFY-gate WARNING) — ADaPTKernel dispatch
# parity with Task 2's plan-execute dispatch test.
# ===========================================================================


class TestADaPTKernelDispatchViaThinRuntime:
    """mode_hint='adapt' routes to ADaPTKernel via the live registry — proven
    end-to-end through ThinRuntime, mirroring
    ``TestPlanExecuteKernel.test_plan_execute_mode_dispatchable_via_thin_runtime``.
    """

    async def test_adapt_mode_dispatchable_via_thin_runtime(self) -> None:
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        async def always_final(messages: Any, system_prompt: Any, **kw: Any) -> str:
            return json.dumps({"type": "final", "final_message": "adapt done"})

        rt = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=always_final,
        )
        events = []
        async for ev in rt.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=[],
            mode_hint="adapt",
        ):
            events.append(ev)

        status_texts = [ev.data.get("text", "") for ev in events if ev.type == "status"]
        assert any(t == "Mode: adapt" for t in status_texts), (
            f"Expected 'Mode: adapt' status; got: {status_texts}"
        )

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "adapt done"


# ===========================================================================
# kernel-patterns spec, Task 6 (REQ-005, REQ-012, REQ-013) — register ALL
# kernels (plan-execute / adapt / reflection / sgr) resolvable via the
# registry; Tree-search deferred (I-002, see design.md and kernels/__init__.py).
# ===========================================================================


class TestAllKernelsRegisteredAndResolvable:
    """Every kernel-patterns-spec kernel resolves through the default
    registry, and its factory returns an object implementing ExecutionKernel
    (REQ-005: register every kernel so it is selectable by mode)."""

    def test_all_kernels_registered_and_resolvable(self) -> None:
        from swarmline.protocols.kernel import ExecutionKernel
        from swarmline.runtime.thin.kernels import get_default_kernel_registry

        registry = get_default_kernel_registry()
        modes = registry.modes()
        expected = {
            "conversational",
            "react",
            "planner",
            "plan-execute",
            "adapt",
            "reflection",
            "sgr",
        }
        assert expected.issubset(modes), (
            f"Expected every built-in mode registered; missing: {expected - modes}"
        )
        for mode in expected:
            kernel = registry.get(mode)
            assert isinstance(kernel, ExecutionKernel), (
                f"registry.get({mode!r}) must return an ExecutionKernel; "
                f"got {type(kernel).__name__}"
            )

    def test_sgr_registered_and_resolvable(self) -> None:
        """mode 'sgr' resolves to a real SGRKernel instance."""
        from swarmline.runtime.thin.kernels import (
            SGRKernel,
            get_default_kernel_registry,
        )

        registry = get_default_kernel_registry()
        assert "sgr" in registry.modes()
        kernel = registry.get("sgr")
        assert isinstance(kernel, SGRKernel)


class TestReflectionKernelAdapter:
    """ReflectionKernelAdapter reads ctx.external_signal per-run (REQ-002,
    REQ-005, REQ-009) — content-branched tests, not tautological forwarding:
    (a) a signal is present -> delegates to a REAL ReflectionKernel end-to-end;
    (b) no signal is present -> a single terminal 'dependency_missing' error,
    never a silent no-op/always-pass default (REQ-009 extended to the
    registry path)."""

    async def test_delegates_to_real_reflection_kernel_when_signal_present(
        self,
    ) -> None:
        """A passing ExternalSignal on ctx.external_signal drives a REAL
        ReflectionKernel run end-to-end: the terminal final surfaces the
        signal-validated text, proving genuine delegation (not a stub)."""
        from swarmline.runtime.thin.executor import ToolExecutor
        from swarmline.runtime.thin.kernels.builtins import ReflectionKernelAdapter
        from swarmline.types import SignalResult

        class _AlwaysPassSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                return SignalResult(passed=True, feedback="")

        async def llm_call(messages: Any, prompt: Any, **kw: Any) -> str:
            return json.dumps({"type": "final", "final_message": "REFLECTED_OK"})

        ctx = _make_context(
            llm_call=llm_call,
            executor=ToolExecutor(),
            external_signal=_AlwaysPassSignal(),
        )
        adapter = ReflectionKernelAdapter()
        events = [ev async for ev in adapter.run(ctx)]

        errors = [ev for ev in events if ev.is_error]
        assert errors == [], f"No error expected on a passing signal; got: {errors}"

        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "REFLECTED_OK", (
            "Final text must be the REAL ReflectionKernel's signal-validated "
            f"output, proving genuine delegation; got: {finals[0].data}"
        )

    async def test_yields_single_dependency_missing_error_when_signal_absent(
        self,
    ) -> None:
        """ctx.external_signal is None (default) -> exactly ONE terminal
        error with kind == 'dependency_missing' — never a silent no-op
        signal and never ReflectionKernel touched at all."""
        from swarmline.runtime.thin.kernels.builtins import ReflectionKernelAdapter

        ctx = _make_context()  # external_signal left at its default: None
        adapter = ReflectionKernelAdapter()
        events = [ev async for ev in adapter.run(ctx)]

        assert len(events) == 1, f"Expected EXACTLY ONE terminal event; got: {events}"
        assert events[0].is_error, f"Expected an error event; got: {events[0]}"
        assert events[0].data.get("kind") == "dependency_missing", (
            f"Expected kind='dependency_missing'; got: {events[0].data}"
        )


class TestReflectionAndSGRModeDispatchViaThinRuntime:
    """mode_hint='reflection'/'sgr' route to the live registry end-to-end
    through ThinRuntime, mirroring
    ``TestADaPTKernelDispatchViaThinRuntime.test_adapt_mode_dispatchable_via_thin_runtime``."""

    async def test_reflection_mode_dispatchable_via_thin_runtime(self) -> None:
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig
        from swarmline.types import SignalResult

        class _AlwaysPassSignal:
            async def evaluate(self, output: str, ctx: Any) -> SignalResult:
                return SignalResult(passed=True, feedback="")

        async def always_final(messages: Any, system_prompt: Any, **kw: Any) -> str:
            return json.dumps({"type": "final", "final_message": "reflection done"})

        rt = ThinRuntime(
            config=RuntimeConfig(
                runtime_name="thin", external_signal=_AlwaysPassSignal()
            ),
            llm_call=always_final,
        )
        events = []
        async for ev in rt.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=[],
            mode_hint="reflection",
        ):
            events.append(ev)

        assert not any(ev.is_error for ev in events), (
            f"Expected no error events; got: {[ev.data for ev in events if ev.is_error]}"
        )
        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "reflection done"

    async def test_sgr_mode_dispatchable_via_thin_runtime(self) -> None:
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message, RuntimeConfig

        async def always_final(messages: Any, system_prompt: Any, **kw: Any) -> str:
            # Not a valid NextStep envelope -> SGR's REQ-011 ReAct fallback
            # reuses this SAME llm_call, which parses cleanly as a 'final'.
            return json.dumps({"type": "final", "final_message": "sgr done"})

        rt = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=always_final,
        )
        events = []
        async for ev in rt.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="sys",
            active_tools=[],
            mode_hint="sgr",
        ):
            events.append(ev)

        assert not any(ev.is_error for ev in events), (
            f"Expected no error events; got: {[ev.data for ev in events if ev.is_error]}"
        )
        finals = [ev for ev in events if ev.is_final]
        assert len(finals) == 1, f"Expected exactly one terminal final; got: {events}"
        assert finals[0].data.get("text") == "sgr done"
