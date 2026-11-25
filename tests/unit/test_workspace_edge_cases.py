"""Edge case tests for workspace components.

Covers conflict detection, double record_read, serialization roundtrip,
mutation policy, session with worktree, and git_local validation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from swarmline.workspace.conflict import ConflictDetector
from swarmline.workspace.git_local import (
    _validate_branch_name,
    _validate_commit_hash,
)
from swarmline.workspace.mutation import MutationPolicy, OwnChangesTracker
from swarmline.workspace.types import (
    ConflictError,
    FileOperationType,
    MutationMode,
    MutationRecord,
    WorkspaceSession,
)

# =====================================================================
# Conflict Detection Edge Cases
# =====================================================================


class TestConflictDetectionEdgeCases:
    def test_conflict_detection_blocks_write_with_hash_mismatch(self) -> None:
        """Hash mismatch between read and check raises ConflictError."""
        detector = ConflictDetector()
        detector.record_read("sess-1", "file.py", "hash_old")

        with pytest.raises(ConflictError) as exc_info:
            detector.check_conflict("sess-1", "file.py", "hash_new")

        assert exc_info.value.expected_hash == "hash_old"
        assert exc_info.value.actual_hash == "hash_new"

    def test_double_record_read_updates_hash(self) -> None:
        """Second record_read for same file updates the recorded hash."""
        detector = ConflictDetector()
        detector.record_read("sess-1", "file.py", "hash_v1")
        detector.record_read("sess-1", "file.py", "hash_v2")

        # check_conflict against new hash passes
        detector.check_conflict("sess-1", "file.py", "hash_v2")

        # check_conflict against old hash raises
        with pytest.raises(ConflictError):
            detector.check_conflict("sess-1", "file.py", "hash_v1")


# =====================================================================
# OwnChangesTracker Serialization
# =====================================================================


class TestOwnChangesTrackerSerialization:
    def test_own_changes_tracker_serialization_roundtrip(self) -> None:
        """to_dict / from_dict preserves mutations and commits."""
        tracker = OwnChangesTracker()
        record = MutationRecord(
            file_path="src/main.py",
            operation=FileOperationType.MODIFY,
            before_hash="aabb",
            after_hash="ccdd",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        )
        tracker.record_mutation("sess-1", record)
        tracker.record_commit("sess-1", "abc123")

        data = tracker.to_dict()
        restored = OwnChangesTracker.from_dict(data)

        mutations = restored.get_mutations("sess-1")
        assert len(mutations) == 1
        assert mutations[0].file_path == "src/main.py"
        assert mutations[0].operation == FileOperationType.MODIFY
        assert mutations[0].before_hash == "aabb"
        assert mutations[0].after_hash == "ccdd"

        assert restored.is_own_commit("sess-1", "abc123") is True
        assert restored.is_own_commit("sess-1", "unknown") is False


# =====================================================================
# Mutation Policy Edge Cases
# =====================================================================


class TestMutationPolicyEdgeCases:
    def test_mutation_policy_auto_apply_allows_all(self) -> None:
        """auto_apply mode allows both writes and deletes."""
        policy = MutationPolicy()
        session = WorkspaceSession.create(
            session_id="s1",
            repo_root="/tmp",
            branch="main",
            mutation_mode=MutationMode.AUTO_APPLY,
        )
        policy.check_write_allowed(session, "any_file.py")
        policy.check_delete_allowed(session, "any_file.py")


# =====================================================================
# WorkspaceSession with worktree
# =====================================================================


class TestWorkspaceSessionWorktree:
    def test_workspace_session_with_worktree_path(self) -> None:
        """WorkspaceSession correctly stores worktree_path."""
        session = WorkspaceSession.create(
            session_id="s1",
            repo_root="/tmp/repo",
            branch="feat/x",
            worktree_path="/tmp/worktrees/feat-x",
        )
        assert session.worktree_path == "/tmp/worktrees/feat-x"
        assert session.repo_root == "/tmp/repo"

        d = session.to_dict()
        assert d["worktree_path"] == "/tmp/worktrees/feat-x"


# =====================================================================
# Git Argument Validation
# =====================================================================


class TestGitLocalValidation:
    @pytest.mark.parametrize(
        "name",
        [
            "feat/my-feature",
            "main",
            "release/v1.0.0",
            "fix_bug",
            "user.name/branch",
        ],
    )
    def test_git_local_validates_branch_name_accepts_valid(self, name: str) -> None:
        assert _validate_branch_name(name) is None

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "feat branch",
            "feat;rm -rf /",
            "feat$(whoami)",
            "feat`id`",
            "feat\nnewline",
            "--flag",
            "-d",
            "--delete",
        ],
    )
    def test_git_local_validates_branch_name_rejects_injection(self, name: str) -> None:
        """Malicious or invalid branch names are rejected."""
        result = _validate_branch_name(name)
        assert result is not None

    @pytest.mark.parametrize(
        "hash_val",
        [
            "abcd",
            "abc123def456",
            "0" * 40,
        ],
    )
    def test_git_local_validates_commit_hash_accepts_valid(self, hash_val: str) -> None:
        assert _validate_commit_hash(hash_val) is None

    @pytest.mark.parametrize(
        "hash_val",
        [
            "",
            "xyz",
            "ABCD1234",
            "abc",
            ";rm -rf /",
            "a" * 41,
            "--flag",
            "-f",
        ],
    )
    def test_git_local_validates_commit_hash_format(self, hash_val: str) -> None:
        """Invalid commit hashes are rejected."""
        result = _validate_commit_hash(hash_val)
        assert result is not None
