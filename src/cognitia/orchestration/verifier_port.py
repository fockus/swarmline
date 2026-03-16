"""VerifierPort — pluggable verification protocol.

Обобщённый Protocol для верификации результатов.
Не привязан к code-specific проверкам (в отличие от CodeVerifier).
Используется GenericWorkflowEngine для произвольных verify/retry loops.
"""

from __future__ import annotations

from typing import Protocol


class VerifierPort(Protocol):
    """Verify execution output. Returns (passed, feedback)."""

    async def verify(self, output: str) -> tuple[bool, str]: ...


class ExecutorPort(Protocol):
    """Execute a goal/task. Returns output string."""

    async def execute(self, goal: str) -> str: ...
