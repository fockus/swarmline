"""Contract tests for MutationPolicyPort, OwnChangesTrackerPort, ConflictDetectorPort.

Every correct implementation MUST pass all these tests.
Tests assert observable behavior through protocol methods only
-- never implementation internals.

Categories:
- MutationPolicy (3 tests)
- OwnChangesTracker (4 tests)
- ConflictDetector (3 tests)

Total: 10 contract tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from swarmline.workspace.protocols import (
    ConflictDetectorPort,
    MutationPolicyPort,
    OwnChangesTrackerPort,
)
from swarmline.workspace.types import (
    ConflictError,
    FileOperationType,
    MutationMode,
    MutationPolicyViolation,
    MutationRecord,
    WorkspaceSession,
)

# =====================================================================
# In-Memory Implementations (contract test subjects)
# =====================================================================


class InMemoryMutationPolicy:
    """Minimal correct MutationPolicyPort implementation."""

    def check_write_allowed(self, session: WorkspaceSession, file_path: str) -> None:
        if session.mutation_mode == MutationMode.READ_ONLY:
            raise MutationPolicyViolation(session.mutation_mode, file_path)

    def check_delete_allowed(self, session: WorkspaceSession, file_path: str) -> None:
        if session.mutation_mode == MutationMode.READ_ONLY:
            raise MutationPolicyViolation(session.mutation_mode, file_path)


class InMemoryOwnChangesTracker:
    """Minimal correct OwnChangesTrackerPort implementation."""

    def __init__(self) -> None:
        self._mutations: dict[str, list[MutationRecord]] = {}
        self._commits: dict[str, set[str]] = {}

    def record_mutation(self, session_id: str, record: MutationRecord) -> None:
        self._mutations.setdefault(session_id, []).append(record)

    def get_mutations(self, session_id: str) -> list[MutationRecord]:
        return list(self._mutations.get(session_id, []))

    def record_commit(self, session_id: str, commit_hash: str) -> None:
        self._commits.setdefault(session_id, set()).add(commit_hash)

    def is_own_commit(self, session_id: str, commit_hash: str) -> bool:
        return commit_hash in self._commits.get(session_id, set())


class InMemoryConflictDetector:
    """Minimal correct ConflictDetectorPort implementation."""

    def __init__(self) -> None:
        self._reads: dict[str, dict[str, str]] = {}

    def record_read(self, session_id: str, file_path: str, content_hash: str) -> None:
        self._reads.setdefault(session_id, {})[file_path] = content_hash

    def check_conflict(
        self, session_id: str, file_path: str, current_hash: str
    ) -> None:
        session_reads = self._reads.get(session_id, {})
        if file_path not in session_reads:
            return
        recorded_hash = session_reads[file_path]
        if recorded_hash != current_hash:
            raise ConflictError(
                file_path, expected_hash=recorded_hash, actual_hash=current_hash
            )


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture(params=["in_memory"])
def mutation_policy(request: pytest.FixtureRequest) -> MutationPolicyPort:
    """Parameterized MutationPolicyPort implementations."""
    impls = {
        "in_memory": InMemoryMutationPolicy,
    }
    return impls[request.param]()


@pytest.fixture(params=["in_memory"])
def own_changes_tracker(request: pytest.FixtureRequest) -> OwnChangesTrackerPort:
    """Parameterized OwnChangesTrackerPort implementations."""
    impls = {
        "in_memory": InMemoryOwnChangesTracker,
    }
    return impls[request.param]()


@pytest.fixture(params=["in_memory"])
def conflict_detector(request: pytest.FixtureRequest) -> ConflictDetectorPort:
    """Parameterized ConflictDetectorPort implementations."""
    impls = {
        "in_memory": InMemoryConflictDetector,
    }
    return impls[request.param]()


@pytest.fixture
def auto_apply_session() -> WorkspaceSession:
    """Session with auto_apply mutation mode."""
    return WorkspaceSession.create(
        session_id="sess-auto",
        repo_root="/tmp/repo",
        branch="main",
        mutation_mode=MutationMode.AUTO_APPLY,
    )


@pytest.fixture
def read_only_session() -> WorkspaceSession:
    """Session with read_only mutation mode."""
    return WorkspaceSession.create(
        session_id="sess-ro",
        repo_root="/tmp/repo",
        branch="main",
        mutation_mode=MutationMode.READ_ONLY,
    )


# =====================================================================
# 1. MutationPolicy Contract (3 tests)
# =====================================================================


class TestMutationPolicyContract:
    """Contract: MutationPolicyPort enforces mutation mode correctly."""

    def test_check_write_allowed_auto_apply_succeeds(
        self,
        mutation_policy: MutationPolicyPort,
        auto_apply_session: WorkspaceSession,
    ) -> None:
        """auto_apply mode allows writes without raising."""
        mutation_policy.check_write_allowed(auto_apply_session, "src/main.py")

    def test_check_write_allowed_read_only_raises_violation(
        self,
        mutation_policy: MutationPolicyPort,
        read_only_session: WorkspaceSession,
    ) -> None:
        """read_only mode raises MutationPolicyViolation on write attempt."""
        with pytest.raises(MutationPolicyViolation) as exc_info:
            mutation_policy.check_write_allowed(read_only_session, "src/main.py")

        assert exc_info.value.mode == MutationMode.READ_ONLY
        assert exc_info.value.file_path == "src/main.py"

    def test_check_delete_allowed_read_only_raises_violation(
        self,
        mutation_policy: MutationPolicyPort,
        read_only_session: WorkspaceSession,
    ) -> None:
        """read_only mode raises MutationPolicyViolation on delete attempt."""
        with pytest.raises(MutationPolicyViolation) as exc_info:
            mutation_policy.check_delete_allowed(read_only_session, "old_file.txt")

        assert exc_info.value.mode == MutationMode.READ_ONLY
        assert exc_info.value.file_path == "old_file.txt"


# =====================================================================
# 2. OwnChangesTracker Contract (4 tests)
# =====================================================================


class TestOwnChangesTrackerContract:
    """Contract: OwnChangesTrackerPort tracks mutations and commits."""

    def test_record_mutation_and_get_mutations_returns_recorded(
        self, own_changes_tracker: OwnChangesTrackerPort
    ) -> None:
        """Recorded mutation appears in get_mutations result."""
        record = MutationRecord(
            file_path="src/main.py",
            operation=FileOperationType.MODIFY,
            before_hash="aabb",
            after_hash="ccdd",
            timestamp=datetime.now(UTC),
        )
        own_changes_tracker.record_mutation("sess-1", record)
        mutations = own_changes_tracker.get_mutations("sess-1")

        assert len(mutations) == 1
        assert mutations[0].file_path == "src/main.py"
        assert mutations[0].operation == FileOperationType.MODIFY
        assert mutations[0].before_hash == "aabb"
        assert mutations[0].after_hash == "ccdd"

    def test_get_mutations_empty_session_returns_empty_list(
        self, own_changes_tracker: OwnChangesTrackerPort
    ) -> None:
        """get_mutations for unknown session returns empty list."""
        mutations = own_changes_tracker.get_mutations("nonexistent-session")

        assert mutations == []

    def test_record_commit_and_is_own_commit_returns_true(
        self, own_changes_tracker: OwnChangesTrackerPort
    ) -> None:
        """Recorded commit hash is recognized as own."""
        own_changes_tracker.record_commit("sess-1", "abc123def456")
        assert own_changes_tracker.is_own_commit("sess-1", "abc123def456") is True

    def test_is_own_commit_unknown_hash_returns_false(
        self, own_changes_tracker: OwnChangesTrackerPort
    ) -> None:
        """Unknown commit hash is not recognized as own."""
        assert own_changes_tracker.is_own_commit("sess-1", "unknown999") is False


# =====================================================================
# 3. ConflictDetector Contract (3 tests)
# =====================================================================


class TestConflictDetectorContract:
    """Contract: ConflictDetectorPort detects hash mismatches."""

    def test_record_read_then_check_conflict_same_hash_passes(
        self, conflict_detector: ConflictDetectorPort
    ) -> None:
        """check_conflict with same hash as recorded read does not raise."""
        conflict_detector.record_read("sess-1", "src/main.py", "hash_abc")
        conflict_detector.check_conflict("sess-1", "src/main.py", "hash_abc")

    def test_record_read_then_check_conflict_different_hash_raises(
        self, conflict_detector: ConflictDetectorPort
    ) -> None:
        """check_conflict with different hash raises ConflictError."""
        conflict_detector.record_read("sess-1", "src/main.py", "hash_abc")

        with pytest.raises(ConflictError) as exc_info:
            conflict_detector.check_conflict("sess-1", "src/main.py", "hash_xyz")

        assert exc_info.value.file_path == "src/main.py"
        assert exc_info.value.expected_hash == "hash_abc"
        assert exc_info.value.actual_hash == "hash_xyz"

    def test_check_conflict_unrecorded_file_passes(
        self, conflict_detector: ConflictDetectorPort
    ) -> None:
        """check_conflict for a file never recorded does not raise."""
        conflict_detector.check_conflict("sess-1", "unknown_file.py", "any_hash")
