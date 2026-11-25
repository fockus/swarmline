"""Fixtures for CodeRuntimePort contract tests.

Provides a parameterized ``adapter`` fixture that injects different
CodeRuntimePort implementations.  Each implementation must pass all
contract tests — that is the whole point of contract testing.

Start with FakeCodeRuntime (raises NotImplementedError everywhere).
Real adapters (Claude, Codex) register themselves here later.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from swarmline.code_runtime_types import (
    CodeRuntimeCapabilities,
    CodeRuntimeConfig,
    CodeRuntimeEvent,
    CodeRuntimeSession,
    CodeSessionStatus,
)
from swarmline.protocols.code_runtime import CodeRuntimePort
from swarmline.runtime.code_runtime.claude import ClaudeCodeRuntimeAdapter
from swarmline.runtime.code_runtime.codex import CodexCodeRuntimeAdapter


class FakeCodeRuntime:
    """Minimal stub that satisfies CodeRuntimePort structurally.

    Every method raises NotImplementedError — used to verify that
    contract tests *collect* (not pass) before real adapters exist.
    """

    async def create_session(self, config: CodeRuntimeConfig) -> CodeRuntimeSession:
        raise NotImplementedError("FakeCodeRuntime.create_session")

    async def execute(
        self, session_id: str, prompt: str
    ) -> AsyncIterator[CodeRuntimeEvent]:
        raise NotImplementedError("FakeCodeRuntime.execute")
        yield  # pragma: no cover — make it an async generator

    async def terminate_session(self, session_id: str) -> None:
        raise NotImplementedError("FakeCodeRuntime.terminate_session")

    def get_capabilities(self) -> CodeRuntimeCapabilities:
        raise NotImplementedError("FakeCodeRuntime.get_capabilities")


class InMemoryCodeRuntime:
    """In-memory CodeRuntimePort implementation for contract testing.

    Provides deterministic behavior without any external dependencies.
    Sessions are stored in a dict; execute yields canned events.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, CodeRuntimeSession] = {}
        self._terminated: set[str] = set()
        self._next_id = 0

    async def create_session(self, config: CodeRuntimeConfig) -> CodeRuntimeSession:
        self._next_id += 1
        sid = f"session-{self._next_id}"
        caps = CodeRuntimeCapabilities(
            provider=config.provider,
            mode="sdk",
            approvals=True,
            subagents=True,
            hooks=True,
            worktrees=True,
            session_persistence=True,
            sandbox=config.sandbox,
        )
        session = CodeRuntimeSession(
            session_id=sid,
            provider=config.provider,
            status=CodeSessionStatus.CREATED,
            capabilities=caps,
            created_at=datetime.now(UTC),
        )
        self._sessions[sid] = session
        return session

    async def execute(
        self, session_id: str, prompt: str
    ) -> AsyncIterator[CodeRuntimeEvent]:
        if session_id in self._terminated:
            raise RuntimeError(f"Session {session_id} is terminated")
        if session_id not in self._sessions:
            raise ValueError(f"Unknown session: {session_id}")
        if not prompt.strip():
            raise ValueError("Prompt must not be empty")

        yield CodeRuntimeEvent.status("Starting execution")
        yield CodeRuntimeEvent.delta(f"Processing: {prompt[:50]}")
        yield CodeRuntimeEvent.tool_use("write_file", {"path": "main.py"})
        yield CodeRuntimeEvent.tool_result(
            "write_file", ok=True, summary="File written"
        )
        yield CodeRuntimeEvent.final(text="Done", session_id=session_id)

    async def terminate_session(self, session_id: str) -> None:
        if session_id not in self._sessions:
            raise ValueError(f"Unknown session: {session_id}")
        self._terminated.add(session_id)

    def get_capabilities(self) -> CodeRuntimeCapabilities:
        return CodeRuntimeCapabilities(
            provider="in_memory",
            mode="sdk",
            approvals=True,
            subagents=True,
            hooks=True,
            worktrees=True,
            session_persistence=True,
            sandbox=True,
        )


@pytest.fixture(params=["in_memory", "claude", "codex"])
def adapter(request: pytest.FixtureRequest) -> CodeRuntimePort:
    """Parameterized fixture injecting CodeRuntimePort implementations."""
    impls: dict[str, Any] = {
        "in_memory": InMemoryCodeRuntime,
        "claude": ClaudeCodeRuntimeAdapter,
        "codex": CodexCodeRuntimeAdapter,
    }
    cls = impls[request.param]
    return cls()


@pytest.fixture
def default_config() -> CodeRuntimeConfig:
    """Reasonable default config for contract tests."""
    return CodeRuntimeConfig(
        provider="claude_code",
        model="claude-sonnet-4-20250514",
        working_directory="/tmp/test",
        approval_mode="auto",
        sandbox=True,
    )
