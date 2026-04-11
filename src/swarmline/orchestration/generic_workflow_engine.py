"""GenericWorkflowEngine - pluggable execute/verify loop.

Generalized CodeWorkflowEngine for professional verifiers and executors.
CodeWorkflowEngine remains as a special case with CodeVerifier.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from swarmline.orchestration.verifier_port import ExecutorPort, VerifierPort

# Type aliases for pluggable executor and verifier
ExecutorFn = Callable[[str, dict[str, Any]], Coroutine[Any, Any, str]]
VerifierFn = Callable[[str, dict[str, Any]], Coroutine[Any, Any, tuple[bool, str]]]


class GenericWorkflowStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    MAX_RETRIES_EXCEEDED = "max_retries_exceeded"


@dataclass(frozen=True, slots=True)
class GenericWorkflowResult:
    """Result of a generic workflow run."""

    status: GenericWorkflowStatus
    output: str = ""
    verification_log: str = ""
    loop_count: int = 0


class GenericWorkflowEngine:
    """Generic Workflow Engine implementation."""

    def __init__(
        self,
        executor: ExecutorPort | ExecutorFn,
        verifier: VerifierPort | VerifierFn,
        max_retries: int = 3,
    ) -> None:
        self._executor = executor
        self._verifier = verifier
        self._max_retries = max_retries

    async def _call_executor(self, task: str, ctx: dict[str, Any]) -> str:
        """Call executor - supports both callable and object-with-execute styles."""
        if hasattr(self._executor, "execute"):
            return await self._executor.execute(task)
        return await self._executor(task, ctx)

    async def _call_verifier(self, output: str, ctx: dict[str, Any]) -> tuple[bool, str]:
        """Call verifier - supports both callable and object-with-verify styles."""
        if hasattr(self._verifier, "verify"):
            return await self._verifier.verify(output)
        return await self._verifier(output, ctx)

    async def run(
        self, task: str, context: dict[str, Any] | None = None
    ) -> GenericWorkflowResult:
        """Execute task with retry/verify loop."""
        ctx = context or {}
        logs: list[str] = []
        output = ""

        for attempt in range(1, self._max_retries + 1):
            output = await self._call_executor(task, ctx)
            passed, message = await self._call_verifier(output, ctx)
            logs.append(f"Attempt {attempt}: {message}")

            if passed:
                return GenericWorkflowResult(
                    status=GenericWorkflowStatus.SUCCESS,
                    output=output,
                    verification_log="\n".join(logs),
                    loop_count=attempt,
                )

        return GenericWorkflowResult(
            status=GenericWorkflowStatus.MAX_RETRIES_EXCEEDED,
            output=output,
            verification_log="\n".join(logs),
            loop_count=self._max_retries,
        )
