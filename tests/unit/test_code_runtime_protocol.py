"""Tests for CodeRuntimePort Protocol.

TDD: RED phase — tests written BEFORE implementation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest

from swarmline.code_runtime_types import (
    CodeRuntimeCapabilities,
    CodeRuntimeConfig,
    CodeRuntimeEvent,
    CodeRuntimeSession,
    CodeSessionStatus,
)


# ---------------------------------------------------------------------------
# A4: CodeRuntimePort — Protocol compliance
# ---------------------------------------------------------------------------


class TestCodeRuntimePortDefinition:
    """CodeRuntimePort must be runtime_checkable with <=5 methods."""

    def test_is_runtime_checkable(self) -> None:
        from swarmline.protocols.code_runtime import CodeRuntimePort

        assert hasattr(CodeRuntimePort, "__protocol_attrs__") or hasattr(
            CodeRuntimePort, "_is_runtime_protocol"
        )

    def test_has_four_or_fewer_public_methods(self) -> None:
        from swarmline.protocols.code_runtime import CodeRuntimePort

        public_methods = [
            name
            for name in dir(CodeRuntimePort)
            if not name.startswith("_")
            and callable(getattr(CodeRuntimePort, name, None))
        ]
        assert len(public_methods) <= 5, f"ISP violation: {public_methods}"

    def test_has_create_session(self) -> None:
        from swarmline.protocols.code_runtime import CodeRuntimePort

        assert hasattr(CodeRuntimePort, "create_session")

    def test_has_execute(self) -> None:
        from swarmline.protocols.code_runtime import CodeRuntimePort

        assert hasattr(CodeRuntimePort, "execute")

    def test_has_terminate_session(self) -> None:
        from swarmline.protocols.code_runtime import CodeRuntimePort

        assert hasattr(CodeRuntimePort, "terminate_session")

    def test_has_get_capabilities(self) -> None:
        from swarmline.protocols.code_runtime import CodeRuntimePort

        assert hasattr(CodeRuntimePort, "get_capabilities")

    def test_only_domain_types_in_module(self) -> None:
        """Protocol module must not import SDK packages."""
        import importlib
        import inspect

        mod = importlib.import_module("swarmline.protocols.code_runtime")
        source = inspect.getsource(mod)
        assert "import anthropic" not in source
        assert "from anthropic" not in source
        assert "import openai" not in source
        assert "from openai" not in source


# ---------------------------------------------------------------------------
# A4: Structural conformance — a fake impl satisfies isinstance check
# ---------------------------------------------------------------------------


class FakeCodeRuntime:
    """Minimal implementation that satisfies CodeRuntimePort."""

    async def create_session(self, config: CodeRuntimeConfig) -> CodeRuntimeSession:
        caps = CodeRuntimeCapabilities(provider="fake", mode="test")
        return CodeRuntimeSession(
            session_id="fake-1",
            provider="fake",
            status=CodeSessionStatus.CREATED,
            capabilities=caps,
            created_at=datetime.now(tz=timezone.utc),
        )

    async def execute(
        self, session_id: str, prompt: str
    ) -> AsyncIterator[CodeRuntimeEvent]:
        yield CodeRuntimeEvent.status("running")
        yield CodeRuntimeEvent.final(text="done", session_id=session_id)

    async def terminate_session(self, session_id: str) -> None:
        pass

    def get_capabilities(self) -> CodeRuntimeCapabilities:
        return CodeRuntimeCapabilities(provider="fake", mode="test")


class TestCodeRuntimePortConformance:
    """FakeCodeRuntime must satisfy the runtime_checkable Protocol."""

    def test_isinstance_check(self) -> None:
        from swarmline.protocols.code_runtime import CodeRuntimePort

        runtime = FakeCodeRuntime()
        assert isinstance(runtime, CodeRuntimePort)

    def test_non_conforming_fails_isinstance(self) -> None:
        from swarmline.protocols.code_runtime import CodeRuntimePort

        class NotARuntime:
            pass

        assert not isinstance(NotARuntime(), CodeRuntimePort)


# ---------------------------------------------------------------------------
# A4: Exported from protocols/__init__.py
# ---------------------------------------------------------------------------


class TestCodeRuntimePortExport:
    """CodeRuntimePort must be importable from protocols package."""

    def test_import_from_protocols_package(self) -> None:
        from swarmline.protocols import CodeRuntimePort

        assert CodeRuntimePort is not None

    def test_in_protocols_all(self) -> None:
        import swarmline.protocols as protocols_mod

        assert "CodeRuntimePort" in protocols_mod.__all__


# ---------------------------------------------------------------------------
# A4: CodeRuntimeConfig (already in code_runtime_types.py, verify frozen)
# ---------------------------------------------------------------------------


class TestCodeRuntimeConfig:
    """CodeRuntimeConfig frozen dataclass."""

    def test_create_with_defaults(self) -> None:
        cfg = CodeRuntimeConfig()
        assert cfg.provider == "claude_code"
        assert cfg.sandbox is True
        assert cfg.working_directory == "."

    def test_create_custom(self) -> None:
        cfg = CodeRuntimeConfig(
            provider="codex",
            model="codex-mini",
            working_directory="/tmp/work",
            approval_mode="manual",
            sandbox=False,
            extra={"timeout": 30},
        )
        assert cfg.provider == "codex"
        assert cfg.extra == {"timeout": 30}

    def test_frozen_immutability(self) -> None:
        from dataclasses import FrozenInstanceError

        cfg = CodeRuntimeConfig()
        with pytest.raises(FrozenInstanceError):
            cfg.provider = "codex"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Edge-case tests (tester-2)
# ---------------------------------------------------------------------------


class _PartialRuntime_MissingExecute:
    """Lacks execute() — must fail isinstance check."""

    async def create_session(
        self, config: CodeRuntimeConfig
    ) -> CodeRuntimeSession: ...  # pragma: no cover

    async def terminate_session(self, session_id: str) -> None: ...  # pragma: no cover

    def get_capabilities(self) -> CodeRuntimeCapabilities: ...  # pragma: no cover


class _PartialRuntime_MissingCreateSession:
    """Lacks create_session() — must fail isinstance check."""

    async def execute(
        self, session_id: str, prompt: str
    ) -> AsyncIterator[CodeRuntimeEvent]:
        yield CodeRuntimeEvent.final(text="x")  # pragma: no cover

    async def terminate_session(self, session_id: str) -> None: ...  # pragma: no cover

    def get_capabilities(self) -> CodeRuntimeCapabilities: ...  # pragma: no cover


class _PartialRuntime_MissingTerminate:
    """Lacks terminate_session() — must fail isinstance check."""

    async def create_session(
        self, config: CodeRuntimeConfig
    ) -> CodeRuntimeSession: ...  # pragma: no cover

    async def execute(
        self, session_id: str, prompt: str
    ) -> AsyncIterator[CodeRuntimeEvent]:
        yield CodeRuntimeEvent.final(text="x")  # pragma: no cover

    def get_capabilities(self) -> CodeRuntimeCapabilities: ...  # pragma: no cover


class _PartialRuntime_MissingGetCapabilities:
    """Lacks get_capabilities() — must fail isinstance check."""

    async def create_session(
        self, config: CodeRuntimeConfig
    ) -> CodeRuntimeSession: ...  # pragma: no cover

    async def execute(
        self, session_id: str, prompt: str
    ) -> AsyncIterator[CodeRuntimeEvent]:
        yield CodeRuntimeEvent.final(text="x")  # pragma: no cover

    async def terminate_session(self, session_id: str) -> None: ...  # pragma: no cover


class TestCodeRuntimePortEdgeCases:
    """Edge-case conformance tests for CodeRuntimePort Protocol."""

    @pytest.mark.parametrize(
        "cls",
        [
            _PartialRuntime_MissingExecute,
            _PartialRuntime_MissingCreateSession,
            _PartialRuntime_MissingTerminate,
            _PartialRuntime_MissingGetCapabilities,
        ],
        ids=[
            "missing_execute",
            "missing_create_session",
            "missing_terminate",
            "missing_get_capabilities",
        ],
    )
    def test_partial_impl_fails_isinstance(self, cls: type) -> None:
        """Missing any single method must fail runtime_checkable isinstance."""
        from swarmline.protocols.code_runtime import CodeRuntimePort

        assert not isinstance(cls(), CodeRuntimePort)

    def test_protocol_method_count_exactly_four(self) -> None:
        from swarmline.protocols.code_runtime import CodeRuntimePort

        public_methods = [
            name
            for name in dir(CodeRuntimePort)
            if not name.startswith("_")
            and callable(getattr(CodeRuntimePort, name, None))
        ]
        assert len(public_methods) == 4, f"Expected 4 methods, got: {public_methods}"

    def test_get_capabilities_is_sync(self) -> None:
        """get_capabilities must be synchronous (not a coroutine function)."""
        import asyncio

        assert not asyncio.iscoroutinefunction(FakeCodeRuntime.get_capabilities)

    def test_create_session_is_async(self) -> None:
        import asyncio

        assert asyncio.iscoroutinefunction(FakeCodeRuntime.create_session)

    def test_terminate_session_is_async(self) -> None:
        import asyncio

        assert asyncio.iscoroutinefunction(FakeCodeRuntime.terminate_session)

    async def test_execute_returns_async_iterator(self) -> None:
        """execute() must return an async iterator of CodeRuntimeEvent."""
        runtime = FakeCodeRuntime()
        cfg = CodeRuntimeConfig()
        session = await runtime.create_session(cfg)
        result = runtime.execute(session.session_id, "test prompt")
        assert hasattr(result, "__aiter__")
        assert hasattr(result, "__anext__")

    async def test_full_lifecycle_through_protocol(self) -> None:
        """Create → execute → collect events → terminate — full contract."""
        runtime = FakeCodeRuntime()
        cfg = CodeRuntimeConfig()

        session = await runtime.create_session(cfg)
        assert session.status == CodeSessionStatus.CREATED

        events: list[CodeRuntimeEvent] = []
        async for evt in runtime.execute(session.session_id, "do something"):
            events.append(evt)
        assert len(events) >= 1
        assert events[-1].is_final

        await runtime.terminate_session(session.session_id)

    def test_capabilities_returns_correct_type(self) -> None:
        runtime = FakeCodeRuntime()
        caps = runtime.get_capabilities()
        assert isinstance(caps, CodeRuntimeCapabilities)
        assert caps.provider == "fake"
