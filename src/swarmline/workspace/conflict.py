"""Optimistic-lock conflict detection for workspace sessions.

In-memory implementation of ConflictDetectorPort.
Domain-pure: stdlib only.
"""

from __future__ import annotations

from swarmline.workspace.types import ConflictError


class ConflictDetector:
    """Detects read-write conflicts via content hash comparison.

    Implements ConflictDetectorPort. Tracks file hashes at read time
    and raises ConflictError if the file changed before write.
    """

    def __init__(self) -> None:
        self._reads: dict[str, dict[str, str]] = {}

    def record_read(self, session_id: str, file_path: str, content_hash: str) -> None:
        """Record the content hash of a file at read time."""
        self._reads.setdefault(session_id, {})[file_path] = content_hash

    def check_conflict(
        self, session_id: str, file_path: str, current_hash: str
    ) -> None:
        """Raise ConflictError if current_hash differs from recorded read hash.

        If no read was recorded for this file, no conflict is possible.
        """
        session_reads = self._reads.get(session_id)
        if session_reads is None:
            return
        recorded_hash = session_reads.get(file_path)
        if recorded_hash is None:
            return
        if recorded_hash != current_hash:
            raise ConflictError(
                file_path=file_path,
                expected_hash=recorded_hash,
                actual_hash=current_hash,
            )
