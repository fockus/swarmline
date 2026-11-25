"""swarmline.storage — generic blob-store primitive (OSS-T10, primitive D).

Public exports
--------------
BlobStorePort      — @runtime_checkable async Protocol (save/get/list/delete).
BlobMeta           — frozen dataclass for blob metadata.
InMemoryBlobStore  — in-memory implementation for tests and dev.
LocalFsBlobStore   — local-filesystem implementation for single-node production.
"""

from __future__ import annotations

from swarmline.storage.blob import (
    BlobMeta,
    BlobStorePort,
    InMemoryBlobStore,
    LocalFsBlobStore,
)

__all__ = [
    "BlobStorePort",
    "BlobMeta",
    "InMemoryBlobStore",
    "LocalFsBlobStore",
]
