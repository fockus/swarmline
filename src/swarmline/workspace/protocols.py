"""Workspace protocols — ISP-compliant ports for safe repo operations.

Each protocol has at most 5 methods. All are @runtime_checkable.
Imports only from workspace.types and orchestration.verification_types.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from swarmline.orchestration.verification_types import VerificationResult
from swarmline.workspace.types import (
    GitOperationResult,
    MutationRecord,
    WorkspaceSession,
)


@runtime_checkable
class GitOperationsPort(Protocol):
    """Port for git operations on a workspace session."""

    async def diff(self, session: WorkspaceSession) -> GitOperationResult: ...
    async def status(self, session: WorkspaceSession) -> GitOperationResult: ...
    async def commit(
        self, session: WorkspaceSession, message: str
    ) -> GitOperationResult: ...
    async def branch_create(
        self, session: WorkspaceSession, name: str
    ) -> GitOperationResult: ...
    async def revert(
        self, session: WorkspaceSession, commit_hash: str
    ) -> GitOperationResult: ...


@runtime_checkable
class MutationPolicyPort(Protocol):
    """Port for enforcing mutation mode constraints.

    Methods raise MutationPolicyViolation if the operation is forbidden.
    """

    def check_write_allowed(self, session: WorkspaceSession, file_path: str) -> None:
        """Raise MutationPolicyViolation if writes are forbidden."""
        ...

    def check_delete_allowed(self, session: WorkspaceSession, file_path: str) -> None:
        """Raise MutationPolicyViolation if deletes are forbidden."""
        ...


@runtime_checkable
class OwnChangesTrackerPort(Protocol):
    """Port for tracking mutations made by the agent itself."""

    def record_mutation(self, session_id: str, record: MutationRecord) -> None: ...
    def get_mutations(self, session_id: str) -> list[MutationRecord]: ...
    def is_own_commit(self, session_id: str, commit_hash: str) -> bool: ...
    def record_commit(self, session_id: str, commit_hash: str) -> None: ...


@runtime_checkable
class ConflictDetectorPort(Protocol):
    """Port for optimistic-lock conflict detection.

    check_conflict raises ConflictError on hash mismatch.
    """

    def record_read(
        self, session_id: str, file_path: str, content_hash: str
    ) -> None: ...

    def check_conflict(
        self, session_id: str, file_path: str, current_hash: str
    ) -> None:
        """Raise ConflictError if current_hash differs from recorded read hash."""
        ...


@runtime_checkable
class VerificationRunnerPort(Protocol):
    """Port for running tests and lints on a workspace session."""

    async def run_tests(
        self, session: WorkspaceSession, command: str | None = None
    ) -> VerificationResult: ...

    async def run_lint(
        self, session: WorkspaceSession, command: str | None = None
    ) -> VerificationResult: ...
