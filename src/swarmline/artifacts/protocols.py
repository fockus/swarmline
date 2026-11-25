"""ArtifactStorePort -- ISP-compliant artifact byte-storage port (<=2 methods).

Mirrors the memory ``sqlite``/``postgres`` swap pattern: :class:`FSArtifactStore`
is the filesystem-backed implementation shipped today; an S3 (or other
object-store) backend is deferred to a later stage.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from swarmline.artifacts.types import Artifact


@runtime_checkable
class ArtifactStorePort(Protocol):
    """Port: persist and retrieve artifact bytes.

    ISP: 2 methods. Any conforming implementation must pass the contract
    tests in ``tests/unit/test_artifact_store_contract.py``.
    """

    async def save(
        self, task_id: str, content: bytes, filename: str, mime_type: str
    ) -> Artifact:
        """Persist ``content`` under ``task_id``/``filename`` and return the Artifact."""
        ...

    async def load(self, artifact: Artifact) -> bytes:
        """Load the bytes previously saved for ``artifact``.

        Raises:
            FileNotFoundError: if the artifact's backing file no longer exists.
        """
        ...
