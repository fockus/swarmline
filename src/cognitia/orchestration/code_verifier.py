"""Code verification protocol and types.

CodeVerifier - ISP-compliant protocol (5 methods) for verifying code quality.
CommandRunner - sandbox-agnostic command execution protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cognitia.orchestration.verification_types import VerificationResult


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Result of a command execution."""

    exit_code: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Sandbox-agnostic command execution."""

    async def run(self, command: str) -> CommandResult: ...


class CodeVerifier(Protocol):
    """ISP: 5 methods for code verification pipeline."""

    async def verify_contracts(self) -> VerificationResult: ...

    async def verify_tests_substantive(self) -> VerificationResult: ...

    async def verify_tests_before_code(self) -> VerificationResult: ...

    async def verify_linters(self) -> VerificationResult: ...

    async def verify_coverage(self, min_pct: int = 85) -> VerificationResult: ...
