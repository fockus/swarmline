"""Contract tests for ExecutionKernel Protocol and KernelContext.

Task 1 of execution-kernel spec (REQ-001, REQ-002, REQ-003).
TDD: these tests are written BEFORE the implementation.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from typing import Any

import pytest

from swarmline.domain_types import RuntimeEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop_checkpoint() -> RuntimeEvent | None:
    return None


async def _noop_llm_call(**kwargs: Any) -> Any:
    return None  # pragma: no cover


def _make_context(**overrides: Any):  # type: ignore[return]
    """Build a minimal valid KernelContext for testing (uses real RuntimeConfig)."""
    from swarmline.runtime.types import RuntimeConfig
    from swarmline.types import KernelContext

    defaults: dict[str, Any] = {
        "llm_call": _noop_llm_call,
        "messages": [],
        "system_prompt": "system",
        "config": RuntimeConfig(runtime_name="thin"),
        "start_time": 0.0,
        "checkpoint": _noop_checkpoint,
    }
    defaults.update(overrides)
    return KernelContext(**defaults)


# ---------------------------------------------------------------------------
# ExecutionKernel Protocol contract (REQ-001, REQ-003)
# ---------------------------------------------------------------------------


class TestExecutionKernelProtocol:
    """ExecutionKernel is @runtime_checkable with exactly 1 method (ISP)."""

    def test_conforming_fake_passes_isinstance_check(self) -> None:
        """A fake kernel with run() satisfies isinstance(x, ExecutionKernel)."""
        from swarmline.types import KernelContext
        from swarmline.protocols import ExecutionKernel

        class FakeKernel:
            def run(self, ctx: KernelContext) -> AsyncIterator[RuntimeEvent]:
                async def _gen():
                    yield RuntimeEvent.status("ok")  # pragma: no cover

                return _gen()

        assert isinstance(FakeKernel(), ExecutionKernel)

    def test_nonconforming_object_fails_isinstance_check(self) -> None:
        """An object without run() does not satisfy isinstance(x, ExecutionKernel)."""
        from swarmline.protocols import ExecutionKernel

        class NotAKernel:
            def execute(self) -> None:  # wrong method name
                pass

        assert not isinstance(NotAKernel(), ExecutionKernel)

    def test_protocol_has_exactly_one_public_method(self) -> None:
        """ExecutionKernel has exactly 1 public method (ISP ≤5, this one has 1)."""
        from swarmline.protocols import ExecutionKernel

        public_methods = [
            name
            for name in dir(ExecutionKernel)
            if not name.startswith("_") and name != "register"
        ]
        assert public_methods == ["run"], (
            f"ExecutionKernel must have exactly 1 method 'run'; got: {public_methods}"
        )

    def test_run_method_exists(self) -> None:
        """ExecutionKernel exposes a run attribute."""
        from swarmline.protocols import ExecutionKernel

        assert hasattr(ExecutionKernel, "run")

    def test_import_from_protocols_package(self) -> None:
        """from swarmline.protocols import ExecutionKernel works."""
        from swarmline.protocols import ExecutionKernel  # noqa: F401

        assert ExecutionKernel is not None


# ---------------------------------------------------------------------------
# KernelContext frozen dataclass (REQ-002)
# ---------------------------------------------------------------------------


class TestKernelContext:
    """KernelContext is a frozen dataclass with required + optional fields."""

    def test_kernel_context_frozen_mutation_raises_frozen_instance_error(
        self,
    ) -> None:
        """Mutating any KernelContext field raises FrozenInstanceError."""
        ctx = _make_context()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.system_prompt = "changed"  # type: ignore[misc]

    def test_kernel_context_optional_fields_default_to_none(self) -> None:
        """executor, tools, on_retry, native_adapter, session_dispatcher,
        external_signal all default None."""
        ctx = _make_context()
        assert ctx.executor is None
        assert ctx.tools is None
        assert ctx.on_retry is None
        assert ctx.native_adapter is None
        assert ctx.session_dispatcher is None
        assert ctx.external_signal is None

    def test_kernel_context_required_fields_stored(self) -> None:
        """Required fields are stored and accessible after construction."""
        ctx = _make_context(system_prompt="Hello", start_time=1.5)
        assert ctx.system_prompt == "Hello"
        assert ctx.start_time == 1.5
        assert ctx.messages == []

    def test_kernel_context_optional_fields_accept_non_none_values(self) -> None:
        """Optional fields store non-None values when supplied."""
        from swarmline.runtime.types import RuntimeConfig
        from swarmline.types import KernelContext

        sentinel = object()
        ctx = KernelContext(
            llm_call=_noop_llm_call,
            messages=[],
            system_prompt="",
            config=RuntimeConfig(runtime_name="thin"),
            start_time=0.0,
            checkpoint=_noop_checkpoint,
            executor=sentinel,  # type: ignore[arg-type]
            tools=["tool_a"],
            on_retry=lambda n, t: None,
            native_adapter=sentinel,  # type: ignore[arg-type]
            session_dispatcher=sentinel,  # type: ignore[arg-type]
        )
        assert ctx.executor is sentinel
        assert ctx.tools == ["tool_a"]
        assert ctx.on_retry is not None
        assert ctx.native_adapter is sentinel
        assert ctx.session_dispatcher is sentinel

    def test_kernel_context_import_from_types_module(self) -> None:
        """from swarmline.types import KernelContext works."""
        from swarmline.types import KernelContext  # noqa: F401

        assert KernelContext is not None

    def test_kernel_context_is_frozen_dataclass(self) -> None:
        """KernelContext is recognized as a frozen dataclass by the stdlib."""
        from swarmline.types import KernelContext

        assert dataclasses.is_dataclass(KernelContext)
        params = dataclasses.fields(KernelContext)
        field_names = {f.name for f in params}
        expected = {
            "llm_call",
            "messages",
            "system_prompt",
            "config",
            "start_time",
            "checkpoint",
            "executor",
            "tools",
            "on_retry",
            "native_adapter",
            "session_dispatcher",
            "external_signal",
            "round_refresher",  # Sprint 1ce CE-9
        }
        assert expected == field_names
