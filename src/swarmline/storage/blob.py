"""Generic blob-store primitive for swarmline (REQ-OSS-051, REQ-OSS-060).

Provides a Protocol + two concrete implementations for storing arbitrary binary
blobs keyed by a ``scope_id`` (e.g. workspace, tenant, session).  Zero product
coupling: all identifiers use generic names (``scope_id``, ``name``,
``blob_id``) and the module carries no swarmline-internal imports beyond stdlib.

Public API
----------
BlobStorePort   — @runtime_checkable Protocol (4 async methods, ISP-compliant).
BlobMeta        — frozen dataclass: id, scope_id, name, content_type,
                  size_bytes, created_at.
InMemoryBlobStore  — in-memory implementation (counter-based ids).
LocalFsBlobStore   — local filesystem implementation (uuid4-based ids, per-
                     scope subdirectory, in-memory metadata index).

Both concrete stores accept an optional ``now_factory`` parameter so that
``created_at`` timestamps are deterministic in tests while defaulting to
``datetime.now(UTC)`` in production.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

# ty 0.0.29 resolves bare 'list' inside a class body against the class scope
# first, so a method named 'list' shadows the builtin in return annotations.
# This module-level alias is looked up in the global scope and is unambiguous.
_List = list


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class BlobMeta:
    """Immutable metadata record for a stored blob."""

    id: str
    scope_id: str
    name: str
    content_type: str
    size_bytes: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------


@runtime_checkable
class BlobStorePort(Protocol):
    """Generic blob-store port (ISP: 4 async methods, no mutations via meta).

    Implementations must be async-safe.  All methods are async so that
    implementations may use async I/O (asyncpg, aiofiles, S3 presign, etc.)
    without requiring a separate adapter layer.
    """

    async def save(
        self,
        scope_id: str,
        name: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Persist *content* under *scope_id/name* and return an opaque blob_id."""
        ...

    async def get(self, blob_id: str) -> tuple[bytes, str] | None:
        """Return ``(content, name)`` for *blob_id*, or ``None`` if not found."""
        ...

    async def list(self, scope_id: str) -> _List[BlobMeta]:
        """Return metadata for all blobs in *scope_id*."""
        ...

    async def delete(self, blob_id: str) -> bool:
        """Remove the blob identified by *blob_id*.  Returns True if deleted."""
        ...


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

_DEFAULT_CONTENT_TYPE = "application/octet-stream"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemoryBlobStore:
    """In-memory BlobStorePort implementation.

    Blob ids use a monotonically incrementing counter formatted as
    ``"blob-NNNNNN"`` (zero-padded to 6 digits).  Suitable for unit tests
    and ephemeral dev environments.

    Parameters
    ----------
    now_factory:
        Callable returning the current datetime for ``BlobMeta.created_at``.
        Defaults to ``datetime.now(UTC)``.  Inject a fixed callable in tests
        to make timestamps deterministic.
    """

    def __init__(self, now_factory: Callable[[], datetime] | None = None) -> None:
        # {blob_id: (content, name, scope_id, content_type)}
        self._store: dict[str, tuple[bytes, str, str, str]] = {}
        self._counter: int = 0
        self._now: Callable[[], datetime] = (
            now_factory if now_factory is not None else _utc_now
        )

    async def save(
        self,
        scope_id: str,
        name: str,
        content: bytes,
        content_type: str = _DEFAULT_CONTENT_TYPE,
    ) -> str:
        self._counter += 1
        blob_id = f"blob-{self._counter:06d}"
        self._store[blob_id] = (content, name, scope_id, content_type)
        return blob_id

    async def get(self, blob_id: str) -> tuple[bytes, str] | None:
        entry = self._store.get(blob_id)
        if entry is None:
            return None
        return entry[0], entry[1]

    async def list(self, scope_id: str) -> _List[BlobMeta]:
        result: _List[BlobMeta] = []
        for blob_id, (content, name, sid, content_type) in self._store.items():
            if sid == scope_id:
                result.append(
                    BlobMeta(
                        id=blob_id,
                        scope_id=sid,
                        name=name,
                        content_type=content_type,
                        size_bytes=len(content),
                        created_at=self._now(),
                    )
                )
        return result

    async def delete(self, blob_id: str) -> bool:
        return self._store.pop(blob_id, None) is not None


class LocalFsBlobStore:
    """Local-filesystem BlobStorePort implementation.

    Blobs are written to ``<base_dir>/<scope_id>/<blob_id>_<name>``.  Blob ids
    are 16-character hex strings derived from ``uuid4()`` (collision probability
    negligible for typical usage volumes).  An in-memory metadata index is kept
    for fast ``list()`` and ``get()`` lookups without scanning the filesystem.

    Parameters
    ----------
    base_dir:
        Root directory under which per-scope subdirectories are created.
    now_factory:
        Callable returning the current datetime for ``BlobMeta.created_at``.
        Defaults to ``datetime.now(UTC)``.  Inject a fixed callable in tests
        to make timestamps deterministic.
    """

    def __init__(
        self,
        base_dir: Path,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._base_dir = base_dir
        self._meta: dict[str, BlobMeta] = {}
        self._now: Callable[[], datetime] = (
            now_factory if now_factory is not None else _utc_now
        )

    async def save(
        self,
        scope_id: str,
        name: str,
        content: bytes,
        content_type: str = _DEFAULT_CONTENT_TYPE,
    ) -> str:
        blob_id = uuid.uuid4().hex[:16]
        # Path-traversal guard — validate before any filesystem operation.
        # An absolute scope_id silently replaces base_dir in a Path join.
        # A '..' component in scope_id, or any path separator / '..' in name,
        # allows escaping base_dir.  Validate both as path objects so the check
        # is filesystem-independent (no resolve() on non-existent paths needed).
        _scope_parts = Path(scope_id).parts
        _name_path = Path(name)
        if Path(scope_id).is_absolute() or ".." in _scope_parts:
            raise ValueError(
                f"Path traversal detected: scope_id={scope_id!r} "
                f"would escape base_dir={self._base_dir!r}"
            )
        if (
            _name_path.is_absolute()
            or len(_name_path.parts) > 1
            or _name_path.name in (".", "..")
        ):
            raise ValueError(
                f"Path traversal detected: name={name!r} "
                f"would escape base_dir={self._base_dir!r}"
            )
        scope_dir = self._base_dir / scope_id
        file_path = scope_dir / f"{blob_id}_{name}"
        scope_dir.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        self._meta[blob_id] = BlobMeta(
            id=blob_id,
            scope_id=scope_id,
            name=name,
            content_type=content_type,
            size_bytes=len(content),
            created_at=self._now(),
        )
        return blob_id

    async def get(self, blob_id: str) -> tuple[bytes, str] | None:
        meta = self._meta.get(blob_id)
        if meta is None:
            return None
        file_path = self._base_dir / meta.scope_id / f"{blob_id}_{meta.name}"
        if not file_path.exists():
            return None
        return file_path.read_bytes(), meta.name

    async def list(self, scope_id: str) -> _List[BlobMeta]:
        return [m for m in self._meta.values() if m.scope_id == scope_id]

    async def delete(self, blob_id: str) -> bool:
        meta = self._meta.pop(blob_id, None)
        if meta is None:
            return False
        file_path = self._base_dir / meta.scope_id / f"{blob_id}_{meta.name}"
        if file_path.exists():
            file_path.unlink()
        return True
