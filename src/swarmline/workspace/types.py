"""Pure domain types for Workspace — zero external/SDK dependencies.

Workspace types form the contract for safe repo/git/worktree operations.
Clean Architecture: no imports from runtime/, infrastructure/, or any SDK.

Types:
- MutationMode: read_only or auto_apply
- WorkspaceSessionStatus: lifecycle states for workspace sessions
- FileOperationType: create, modify, delete
- WorkspaceSession: frozen session snapshot with factory create()
- GitOperationResult: result of a git operation
- MutationRecord: single file mutation record
- MutationPolicyViolation: raised when mutation mode forbids a write/delete
- ConflictError: raised on optimistic-lock hash mismatch
- compute_content_hash: SHA-256 content fingerprint (16 hex chars)
"""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Enums (str for JSON serialization / extensibility)
# ---------------------------------------------------------------------------


class MutationMode(enum.StrEnum):
    """Controls whether a workspace session may modify files."""

    READ_ONLY = "read_only"
    AUTO_APPLY = "auto_apply"


class WorkspaceSessionStatus(enum.StrEnum):
    """Lifecycle states for a workspace session."""

    ACTIVE = "active"
    COMMITTED = "committed"
    ABANDONED = "abandoned"
    ERROR = "error"


class FileOperationType(enum.StrEnum):
    """Kind of file mutation tracked by the workspace."""

    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"


# ---------------------------------------------------------------------------
# WorkspaceSession
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkspaceSession:
    """Immutable snapshot of a workspace session.

    Use the ``create`` classmethod for construction with validation.
    """

    session_id: str
    repo_root: str
    branch: str
    worktree_path: str | None
    env_profile: dict[str, str]
    mutation_mode: MutationMode
    runtime_session_id: str | None
    status: WorkspaceSessionStatus
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        repo_root: str,
        branch: str,
        worktree_path: str | None = None,
        env_profile: dict[str, str] | None = None,
        mutation_mode: MutationMode = MutationMode.READ_ONLY,
        runtime_session_id: str | None = None,
        status: WorkspaceSessionStatus = WorkspaceSessionStatus.ACTIVE,
        created_at: datetime | None = None,
    ) -> WorkspaceSession:
        """Create a WorkspaceSession with validation.

        Raises:
            ValueError: If session_id, repo_root, or branch are empty.
        """
        if not session_id:
            raise ValueError("session_id must not be empty")
        if not repo_root:
            raise ValueError("repo_root must not be empty")
        if not branch:
            raise ValueError("branch must not be empty")

        return cls(
            session_id=session_id,
            repo_root=repo_root,
            branch=branch,
            worktree_path=worktree_path,
            env_profile=env_profile if env_profile is not None else {},
            mutation_mode=mutation_mode,
            runtime_session_id=runtime_session_id,
            status=status,
            created_at=created_at if created_at is not None else datetime.now(UTC),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (no SDK types)."""
        return {
            "session_id": self.session_id,
            "repo_root": self.repo_root,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "env_profile": dict(self.env_profile),
            "mutation_mode": self.mutation_mode.value,
            "runtime_session_id": self.runtime_session_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# GitOperationResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GitOperationResult:
    """Result of a git operation (diff, status, commit, etc.)."""

    success: bool
    output: str
    changed_files: tuple[str, ...] = ()
    error: str | None = None
    operation: str = ""


# ---------------------------------------------------------------------------
# MutationRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutationRecord:
    """Record of a single file mutation within a workspace session."""

    file_path: str
    operation: FileOperationType
    before_hash: str | None
    after_hash: str | None
    timestamp: datetime


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MutationPolicyViolation(Exception):
    """Raised when a mutation is forbidden by the current mode."""

    def __init__(self, mode: MutationMode, file_path: str, message: str = "") -> None:
        self.mode = mode
        self.file_path = file_path
        self.message = message or (
            f"Mutation forbidden: mode={mode.value}, file={file_path}"
        )
        super().__init__(self.message)


class ConflictError(Exception):
    """Raised on optimistic-lock hash mismatch (read-write conflict)."""

    def __init__(self, file_path: str, expected_hash: str, actual_hash: str) -> None:
        self.file_path = file_path
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        super().__init__(
            f"Conflict on {file_path}: expected {expected_hash}, got {actual_hash}"
        )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def compute_content_hash(content: str) -> str:
    """SHA-256 content fingerprint, truncated to 16 hex characters."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
