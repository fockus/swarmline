"""FSArtifactStore -- filesystem-backed ArtifactStorePort implementation.

Ported from Aura's ``infrastructure/artifacts/fs_artifact_store.py``. Files are
stored under ``{base_path}/{task_id}/{artifact_id}_{filename}``. S3/other
object-store backends are deferred (see the ArtifactStorePort docstring).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from swarmline.artifacts.types import Artifact, ArtifactType
from swarmline.path_safety import validate_namespace_segment


def _reject_filename_traversal(filename: str) -> None:
    """Reject empty/absolute/traversal filenames (lighter than a namespace segment)."""
    if not filename or filename in {".", ".."} or ".." in filename:
        raise ValueError(f"Invalid filename: {filename!r}")
    if filename.startswith(("/", "\\")):
        raise ValueError(f"Invalid filename: {filename!r}")


class FSArtifactStore:
    """Filesystem implementation of :class:`~swarmline.artifacts.protocols.ArtifactStorePort`."""

    def __init__(self, base_path: str | Path = "data/artifacts") -> None:
        self._base_path = Path(base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)

    @property
    def base_path(self) -> Path:
        """Root directory this store writes under (used for path-traversal guards)."""
        return self._base_path

    async def save(
        self, task_id: str, content: bytes, filename: str, mime_type: str
    ) -> Artifact:
        """Save ``content`` under ``{base_path}/{task_id}/`` and return the Artifact."""
        validate_namespace_segment(task_id, "task_id")
        _reject_filename_traversal(filename)

        task_dir = self._base_path / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        artifact_id = f"art_{uuid.uuid4().hex[:12]}"
        file_path = task_dir / f"{artifact_id}_{filename}"
        file_path.write_bytes(content)

        return Artifact(
            id=artifact_id,
            type=ArtifactType.TOOL_OUTPUT,
            title=filename,
            path=file_path,
            mime_type=mime_type,
            size_bytes=len(content),
        )

    async def load(self, artifact: Artifact) -> bytes:
        """Load bytes for ``artifact`` from disk."""
        path = Path(artifact.path)
        if not path.exists():
            raise FileNotFoundError(f"Artifact not found: {artifact.path}")
        return path.read_bytes()
