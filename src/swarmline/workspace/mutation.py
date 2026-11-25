"""Mutation policy enforcement and own-changes tracking.

In-memory implementations of MutationPolicyPort and OwnChangesTrackerPort.
Domain-pure: stdlib only.
"""

from __future__ import annotations

from typing import Any, cast

from swarmline.workspace.types import (
    MutationMode,
    MutationPolicyViolation,
    MutationRecord,
    WorkspaceSession,
    compute_content_hash,
)


class MutationPolicy:
    """Enforces mutation mode constraints on workspace sessions.

    Implements MutationPolicyPort.
    """

    def check_write_allowed(self, session: WorkspaceSession, file_path: str) -> None:
        """Raise MutationPolicyViolation if session is read-only."""
        if session.mutation_mode == MutationMode.READ_ONLY:
            raise MutationPolicyViolation(
                mode=session.mutation_mode,
                file_path=file_path,
                message=f"Write forbidden in read_only mode: {file_path}",
            )

    def check_delete_allowed(self, session: WorkspaceSession, file_path: str) -> None:
        """Raise MutationPolicyViolation if session is read-only."""
        if session.mutation_mode == MutationMode.READ_ONLY:
            raise MutationPolicyViolation(
                mode=session.mutation_mode,
                file_path=file_path,
                message=f"Delete forbidden in read_only mode: {file_path}",
            )


class OwnChangesTracker:
    """Tracks mutations and commits made by the agent.

    Implements OwnChangesTrackerPort. In-memory storage with serialization.
    """

    def __init__(self) -> None:
        self._mutations: dict[str, list[MutationRecord]] = {}
        self._commits: dict[str, set[str]] = {}

    def record_mutation(self, session_id: str, record: MutationRecord) -> None:
        """Record a file mutation for a session."""
        self._mutations.setdefault(session_id, []).append(record)

    def get_mutations(self, session_id: str) -> list[MutationRecord]:
        """Return all recorded mutations for a session."""
        return list(self._mutations.get(session_id, []))

    def record_commit(self, session_id: str, commit_hash: str) -> None:
        """Record a commit hash as owned by a session."""
        self._commits.setdefault(session_id, set()).add(commit_hash)

    def is_own_commit(self, session_id: str, commit_hash: str) -> bool:
        """Check if a commit was made by this session."""
        return commit_hash in self._commits.get(session_id, set())

    def to_dict(self) -> dict[str, object]:
        """Serialize tracker state for persistence."""
        return {
            "mutations": {
                sid: [
                    {
                        "file_path": r.file_path,
                        "operation": r.operation.value,
                        "before_hash": r.before_hash,
                        "after_hash": r.after_hash,
                        "timestamp": r.timestamp.isoformat(),
                    }
                    for r in records
                ]
                for sid, records in self._mutations.items()
            },
            "commits": {sid: sorted(hashes) for sid, hashes in self._commits.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> OwnChangesTracker:
        """Restore tracker state from serialized dict."""
        from datetime import UTC, datetime

        from swarmline.workspace.types import FileOperationType

        tracker = cls()
        mutations_data = data.get("mutations", {})
        if isinstance(mutations_data, dict):
            for sid, records in mutations_data.items():
                if isinstance(records, list):
                    for r in records:
                        if isinstance(r, dict):
                            entry = cast("dict[str, Any]", r)
                            tracker.record_mutation(
                                str(sid),
                                MutationRecord(
                                    file_path=str(entry["file_path"]),
                                    operation=FileOperationType(entry["operation"]),
                                    before_hash=entry.get("before_hash"),
                                    after_hash=entry.get("after_hash"),
                                    timestamp=datetime.fromisoformat(
                                        str(entry["timestamp"])
                                    ).astimezone(UTC)
                                    if "timestamp" in entry
                                    else datetime.now(UTC),
                                ),
                            )
        commits_data = data.get("commits", {})
        if isinstance(commits_data, dict):
            for sid, hashes in commits_data.items():
                if isinstance(hashes, list):
                    for h in hashes:
                        tracker.record_commit(str(sid), str(h))
        return tracker


# Re-export compute_content_hash for convenience (same module family)
__all__ = ["MutationPolicy", "OwnChangesTracker", "compute_content_hash"]
