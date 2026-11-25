"""Tests for workspace domain types — WorkspaceSession, GitOperationResult, MutationRecord,
MutationPolicyViolation, ConflictError, compute_content_hash.

TDD: tests against the types defined in swarmline.workspace.types.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from swarmline.workspace.types import (
    ConflictError,
    FileOperationType,
    GitOperationResult,
    MutationMode,
    MutationPolicyViolation,
    MutationRecord,
    WorkspaceSession,
    WorkspaceSessionStatus,
    compute_content_hash,
)

# ---------------------------------------------------------------------------
# WorkspaceSession
# ---------------------------------------------------------------------------


class TestWorkspaceSessionCreate:
    """WorkspaceSession.create() factory validation and defaults."""

    def test_workspace_session_create_valid_binds_all_fields(self) -> None:
        now = datetime(2026, 4, 12, tzinfo=UTC)
        session = WorkspaceSession.create(
            session_id="ws-001",
            repo_root="/repos/taskloom",
            branch="feat/workspace",
            worktree_path="/tmp/wt-001",
            env_profile={"PYTHONPATH": "/src"},
            mutation_mode=MutationMode.AUTO_APPLY,
            runtime_session_id="rt-42",
            status=WorkspaceSessionStatus.ACTIVE,
            created_at=now,
        )
        assert session.session_id == "ws-001"
        assert session.repo_root == "/repos/taskloom"
        assert session.branch == "feat/workspace"
        assert session.worktree_path == "/tmp/wt-001"
        assert session.env_profile == {"PYTHONPATH": "/src"}
        assert session.mutation_mode == MutationMode.AUTO_APPLY
        assert session.runtime_session_id == "rt-42"
        assert session.status == WorkspaceSessionStatus.ACTIVE
        assert session.created_at == now

    def test_workspace_session_create_defaults_mutation_mode_to_read_only(self) -> None:
        session = WorkspaceSession.create(
            session_id="ws-002",
            repo_root="/repos/x",
            branch="main",
        )
        assert session.mutation_mode == MutationMode.READ_ONLY

    def test_workspace_session_create_defaults_status_to_active(self) -> None:
        session = WorkspaceSession.create(
            session_id="ws-003",
            repo_root="/repos/x",
            branch="main",
        )
        assert session.status == WorkspaceSessionStatus.ACTIVE

    def test_workspace_session_create_defaults_env_profile_to_empty_dict(self) -> None:
        session = WorkspaceSession.create(
            session_id="ws-004",
            repo_root="/repos/x",
            branch="main",
        )
        assert session.env_profile == {}

    def test_workspace_session_create_defaults_created_at_to_now(self) -> None:
        before = datetime.now(UTC)
        session = WorkspaceSession.create(
            session_id="ws-005",
            repo_root="/repos/x",
            branch="main",
        )
        after = datetime.now(UTC)
        assert before <= session.created_at <= after

    def test_workspace_session_create_defaults_worktree_path_to_none(self) -> None:
        session = WorkspaceSession.create(
            session_id="ws-006",
            repo_root="/repos/x",
            branch="main",
        )
        assert session.worktree_path is None

    def test_workspace_session_create_defaults_runtime_session_id_to_none(self) -> None:
        session = WorkspaceSession.create(
            session_id="ws-007",
            repo_root="/repos/x",
            branch="main",
        )
        assert session.runtime_session_id is None


class TestWorkspaceSessionImmutability:
    """WorkspaceSession is frozen — mutation must raise."""

    def test_workspace_session_is_frozen_raises_on_mutation(self) -> None:
        session = WorkspaceSession.create(
            session_id="ws-010",
            repo_root="/repos/x",
            branch="main",
        )
        with pytest.raises(FrozenInstanceError):
            session.status = WorkspaceSessionStatus.ERROR  # type: ignore[misc]


class TestWorkspaceSessionToDict:
    """to_dict() serialization roundtrip."""

    def test_workspace_session_to_dict_roundtrip(self) -> None:
        now = datetime(2026, 4, 12, tzinfo=UTC)
        session = WorkspaceSession.create(
            session_id="ws-020",
            repo_root="/repos/taskloom",
            branch="main",
            worktree_path="/tmp/wt",
            env_profile={"KEY": "val"},
            mutation_mode=MutationMode.AUTO_APPLY,
            runtime_session_id="rt-1",
            status=WorkspaceSessionStatus.COMMITTED,
            created_at=now,
        )
        d = session.to_dict()

        assert d["session_id"] == "ws-020"
        assert d["repo_root"] == "/repos/taskloom"
        assert d["branch"] == "main"
        assert d["worktree_path"] == "/tmp/wt"
        assert d["env_profile"] == {"KEY": "val"}
        assert d["mutation_mode"] == "auto_apply"
        assert d["runtime_session_id"] == "rt-1"
        assert d["status"] == "committed"
        assert d["created_at"] == now.isoformat()

    def test_workspace_session_to_dict_consistent(self) -> None:
        session = WorkspaceSession.create(
            session_id="ws-021",
            repo_root="/repos/x",
            branch="main",
        )
        assert session.to_dict() == session.to_dict()


class TestWorkspaceSessionValidation:
    """create() rejects invalid inputs."""

    def test_workspace_session_create_empty_repo_root_raises(self) -> None:
        with pytest.raises(ValueError, match="repo_root"):
            WorkspaceSession.create(
                session_id="ws-030",
                repo_root="",
                branch="main",
            )

    def test_workspace_session_create_empty_branch_raises(self) -> None:
        with pytest.raises(ValueError, match="branch"):
            WorkspaceSession.create(
                session_id="ws-031",
                repo_root="/repos/x",
                branch="",
            )

    def test_workspace_session_create_empty_session_id_raises(self) -> None:
        with pytest.raises(ValueError, match="session_id"):
            WorkspaceSession.create(
                session_id="",
                repo_root="/repos/x",
                branch="main",
            )

    def test_workspace_session_session_id_is_uuid_format(self) -> None:
        uid = str(uuid.uuid4())
        session = WorkspaceSession.create(
            session_id=uid,
            repo_root="/repos/x",
            branch="main",
        )
        assert session.session_id == uid
        uuid.UUID(session.session_id)


# ---------------------------------------------------------------------------
# GitOperationResult
# ---------------------------------------------------------------------------


class TestGitOperationResult:
    """GitOperationResult frozen dataclass."""

    def test_git_operation_result_success_has_empty_error(self) -> None:
        result = GitOperationResult(
            success=True,
            output="diff output here",
            changed_files=("file.py",),
            operation="diff",
        )
        assert result.success is True
        assert result.error is None

    def test_git_operation_result_failure_has_error_message(self) -> None:
        result = GitOperationResult(
            success=False,
            output="",
            error="fatal: not a git repository",
            operation="status",
        )
        assert result.success is False
        assert result.error == "fatal: not a git repository"

    def test_git_operation_result_defaults(self) -> None:
        result = GitOperationResult(success=True, output="ok")
        assert result.changed_files == ()
        assert result.error is None
        assert result.operation == ""

    def test_git_operation_result_is_frozen(self) -> None:
        result = GitOperationResult(success=True, output="ok")
        with pytest.raises(FrozenInstanceError):
            result.success = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MutationRecord
# ---------------------------------------------------------------------------


class TestMutationRecord:
    """MutationRecord frozen dataclass."""

    def test_mutation_record_fields_are_immutable(self) -> None:
        now = datetime.now(UTC)
        record = MutationRecord(
            file_path="src/main.py",
            operation=FileOperationType.MODIFY,
            before_hash="abc123",
            after_hash="def456",
            timestamp=now,
        )
        with pytest.raises(FrozenInstanceError):
            record.file_path = "other.py"  # type: ignore[misc]

    def test_mutation_record_stores_all_fields(self) -> None:
        now = datetime(2026, 4, 12, tzinfo=UTC)
        record = MutationRecord(
            file_path="src/app.py",
            operation=FileOperationType.CREATE,
            before_hash=None,
            after_hash="aabbccdd",
            timestamp=now,
        )
        assert record.file_path == "src/app.py"
        assert record.operation == FileOperationType.CREATE
        assert record.before_hash is None
        assert record.after_hash == "aabbccdd"
        assert record.timestamp == now


# ---------------------------------------------------------------------------
# MutationPolicyViolation
# ---------------------------------------------------------------------------


class TestMutationPolicyViolation:
    """MutationPolicyViolation exception carries mode and path."""

    def test_mutation_policy_violation_contains_mode_and_path(self) -> None:
        exc = MutationPolicyViolation(
            mode=MutationMode.READ_ONLY,
            file_path="src/secret.py",
        )
        assert exc.mode == MutationMode.READ_ONLY
        assert exc.file_path == "src/secret.py"
        assert "read_only" in str(exc)
        assert "src/secret.py" in str(exc)

    def test_mutation_policy_violation_custom_message(self) -> None:
        exc = MutationPolicyViolation(
            mode=MutationMode.READ_ONLY,
            file_path="x.py",
            message="custom error",
        )
        assert exc.message == "custom error"
        assert str(exc) == "custom error"

    def test_mutation_policy_violation_is_exception(self) -> None:
        exc = MutationPolicyViolation(
            mode=MutationMode.READ_ONLY,
            file_path="x.py",
        )
        assert isinstance(exc, Exception)
        with pytest.raises(MutationPolicyViolation):
            raise exc


# ---------------------------------------------------------------------------
# ConflictError
# ---------------------------------------------------------------------------


class TestConflictError:
    """ConflictError exception carries hashes."""

    def test_conflict_error_contains_expected_and_actual_hash(self) -> None:
        exc = ConflictError(
            file_path="src/main.py",
            expected_hash="aabb1122",
            actual_hash="ccdd3344",
        )
        assert exc.file_path == "src/main.py"
        assert exc.expected_hash == "aabb1122"
        assert exc.actual_hash == "ccdd3344"
        assert "aabb1122" in str(exc)
        assert "ccdd3344" in str(exc)
        assert "src/main.py" in str(exc)

    def test_conflict_error_is_exception(self) -> None:
        exc = ConflictError(
            file_path="x.py",
            expected_hash="a",
            actual_hash="b",
        )
        assert isinstance(exc, Exception)
        with pytest.raises(ConflictError):
            raise exc


# ---------------------------------------------------------------------------
# compute_content_hash
# ---------------------------------------------------------------------------


class TestComputeContentHash:
    """SHA-256 content fingerprint utility."""

    def test_compute_content_hash_deterministic(self) -> None:
        h1 = compute_content_hash("hello world")
        h2 = compute_content_hash("hello world")
        assert h1 == h2

    def test_compute_content_hash_different_content_different_hash(self) -> None:
        h1 = compute_content_hash("hello")
        h2 = compute_content_hash("world")
        assert h1 != h2

    def test_compute_content_hash_returns_16_hex_chars(self) -> None:
        h = compute_content_hash("test content")
        assert len(h) == 16
        assert re.fullmatch(r"[0-9a-f]{16}", h)

    def test_compute_content_hash_empty_string(self) -> None:
        h = compute_content_hash("")
        assert len(h) == 16
        assert re.fullmatch(r"[0-9a-f]{16}", h)


# ---------------------------------------------------------------------------
# Enum completeness
# ---------------------------------------------------------------------------


class TestEnums:
    """Verify enum members."""

    @pytest.mark.parametrize("member", ["READ_ONLY", "AUTO_APPLY"])
    def test_mutation_mode_has_member(self, member: str) -> None:
        assert hasattr(MutationMode, member)

    @pytest.mark.parametrize("member", ["ACTIVE", "COMMITTED", "ABANDONED", "ERROR"])
    def test_workspace_session_status_has_member(self, member: str) -> None:
        assert hasattr(WorkspaceSessionStatus, member)

    @pytest.mark.parametrize("member", ["CREATE", "MODIFY", "DELETE"])
    def test_file_operation_type_has_member(self, member: str) -> None:
        assert hasattr(FileOperationType, member)

    def test_mutation_mode_count(self) -> None:
        assert len(MutationMode) == 2

    def test_workspace_session_status_count(self) -> None:
        assert len(WorkspaceSessionStatus) == 4

    def test_file_operation_type_count(self) -> None:
        assert len(FileOperationType) == 3
