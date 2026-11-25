"""CodeRuntimePort — Protocol for coding agent runtimes.

ISP: 4 public methods (create_session, execute, terminate_session, get_capabilities).
Dependencies: only domain types from code_runtime_types (zero SDK imports).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from swarmline.code_runtime_types import (
    CodeRuntimeCapabilities,
    CodeRuntimeConfig,
    CodeRuntimeEvent,
    CodeRuntimeSession,
)


@runtime_checkable
class CodeRuntimePort(Protocol):
    """Port for coding agent runtimes (Claude Code, Codex, etc.).

    ISP-compliant: 4 methods, all using domain types only.
    """

    async def create_session(self, config: CodeRuntimeConfig) -> CodeRuntimeSession: ...

    def execute(
        self, session_id: str, prompt: str
    ) -> AsyncIterator[CodeRuntimeEvent]: ...

    async def terminate_session(self, session_id: str) -> None: ...

    def get_capabilities(self) -> CodeRuntimeCapabilities: ...
