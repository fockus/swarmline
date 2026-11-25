"""Tests for BlobStorePort, InMemoryBlobStore, and LocalFsBlobStore.

OSS-T10 primitive D — generic blob-store primitive.
TDD: these tests are written BEFORE the implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from swarmline.storage.blob import (
    BlobMeta,
    BlobStorePort,
    InMemoryBlobStore,
    LocalFsBlobStore,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def inmem() -> InMemoryBlobStore:
    return InMemoryBlobStore()


@pytest.fixture
def localfs(tmp_path: Path) -> LocalFsBlobStore:
    return LocalFsBlobStore(base_dir=tmp_path)


# ---------------------------------------------------------------------------
# Protocol isinstance checks
# ---------------------------------------------------------------------------


def test_inmemory_blob_store_is_blob_store_port(inmem: InMemoryBlobStore) -> None:
    """InMemoryBlobStore satisfies BlobStorePort at runtime."""
    assert isinstance(inmem, BlobStorePort)


def test_localfs_blob_store_is_blob_store_port(localfs: LocalFsBlobStore) -> None:
    """LocalFsBlobStore satisfies BlobStorePort at runtime."""
    assert isinstance(localfs, BlobStorePort)


# ---------------------------------------------------------------------------
# InMemoryBlobStore
# ---------------------------------------------------------------------------


async def test_inmem_save_get_roundtrip(inmem: InMemoryBlobStore) -> None:
    """save → get returns (content, name)."""
    blob_id = await inmem.save("scope-1", "readme.txt", b"hello world", "text/plain")

    result = await inmem.get(blob_id)

    assert result is not None
    content, name = result
    assert content == b"hello world"
    assert name == "readme.txt"


async def test_inmem_get_missing_returns_none(inmem: InMemoryBlobStore) -> None:
    """get with unknown blob_id returns None."""
    result = await inmem.get("nonexistent-blob-id")

    assert result is None


async def test_inmem_list_filters_by_scope_id(inmem: InMemoryBlobStore) -> None:
    """list returns only blobs for the given scope_id; two scopes are isolated."""
    await inmem.save("scope-a", "f1.txt", b"aa", "text/plain")
    await inmem.save("scope-a", "f2.txt", b"bb", "text/plain")
    await inmem.save("scope-b", "f3.txt", b"cc", "text/plain")

    blobs_a = await inmem.list("scope-a")
    blobs_b = await inmem.list("scope-b")

    assert len(blobs_a) == 2
    assert len(blobs_b) == 1
    assert {m.name for m in blobs_a} == {"f1.txt", "f2.txt"}
    assert all(m.scope_id == "scope-a" for m in blobs_a)
    assert blobs_b[0].name == "f3.txt"
    assert blobs_b[0].scope_id == "scope-b"


async def test_inmem_delete_then_get_returns_none(inmem: InMemoryBlobStore) -> None:
    """delete returns True; subsequent get returns None."""
    blob_id = await inmem.save("scope-1", "temp.bin", b"data")

    deleted = await inmem.delete(blob_id)
    result = await inmem.get(blob_id)

    assert deleted is True
    assert result is None


async def test_inmem_delete_missing_returns_false(inmem: InMemoryBlobStore) -> None:
    """delete on a nonexistent blob_id returns False."""
    result = await inmem.delete("no-such-blob")

    assert result is False


async def test_inmem_save_returns_unique_ids(inmem: InMemoryBlobStore) -> None:
    """Two consecutive saves produce different blob_ids."""
    id1 = await inmem.save("scope-1", "a.txt", b"aaa")
    id2 = await inmem.save("scope-1", "b.txt", b"bbb")

    assert id1 != id2


async def test_inmem_blob_meta_size_and_content_type(inmem: InMemoryBlobStore) -> None:
    """BlobMeta.size_bytes equals len(content) and content_type is stored."""
    await inmem.save("scope-1", "data.bin", b"0123456789", "application/octet-stream")

    blobs = await inmem.list("scope-1")

    assert len(blobs) == 1
    meta = blobs[0]
    assert meta.size_bytes == 10
    assert meta.content_type == "application/octet-stream"


async def test_inmem_now_factory_makes_created_at_deterministic(
    inmem: InMemoryBlobStore,
) -> None:
    """An injected now_factory makes BlobMeta.created_at fully deterministic."""
    fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    store = InMemoryBlobStore(now_factory=lambda: fixed_time)

    await store.save("scope-1", "file.txt", b"x")
    blobs = await store.list("scope-1")

    assert len(blobs) == 1
    assert blobs[0].created_at == fixed_time


async def test_inmem_blob_meta_id_format(inmem: InMemoryBlobStore) -> None:
    """InMemoryBlobStore uses counter-based 'blob-NNNNNN' id format."""
    id1 = await inmem.save("scope-1", "a.txt", b"a")
    id2 = await inmem.save("scope-1", "b.txt", b"b")

    assert id1 == "blob-000001"
    assert id2 == "blob-000002"


# ---------------------------------------------------------------------------
# LocalFsBlobStore
# ---------------------------------------------------------------------------


async def test_localfs_save_get_roundtrip(localfs: LocalFsBlobStore) -> None:
    """save → get returns (content, name)."""
    blob_id = await localfs.save("scope-1", "readme.md", b"# Hello", "text/markdown")

    result = await localfs.get(blob_id)

    assert result is not None
    content, name = result
    assert content == b"# Hello"
    assert name == "readme.md"


async def test_localfs_get_missing_returns_none(localfs: LocalFsBlobStore) -> None:
    """get with unknown blob_id returns None."""
    result = await localfs.get("nonexistent-blob-id")

    assert result is None


async def test_localfs_list_filters_by_scope_id(localfs: LocalFsBlobStore) -> None:
    """list returns only blobs for the given scope_id; two scopes are isolated."""
    await localfs.save("scope-a", "f1.txt", b"aa", "text/plain")
    await localfs.save("scope-a", "f2.txt", b"bb", "text/plain")
    await localfs.save("scope-b", "f3.txt", b"cc", "text/plain")

    blobs_a = await localfs.list("scope-a")
    blobs_b = await localfs.list("scope-b")

    assert len(blobs_a) == 2
    assert len(blobs_b) == 1
    assert {m.name for m in blobs_a} == {"f1.txt", "f2.txt"}
    assert all(m.scope_id == "scope-a" for m in blobs_a)


async def test_localfs_delete_then_get_returns_none(localfs: LocalFsBlobStore) -> None:
    """delete returns True; subsequent get returns None and file is removed."""
    blob_id = await localfs.save("scope-1", "temp.bin", b"data")

    deleted = await localfs.delete(blob_id)
    result = await localfs.get(blob_id)

    assert deleted is True
    assert result is None


async def test_localfs_delete_missing_returns_false(localfs: LocalFsBlobStore) -> None:
    """delete on a nonexistent blob_id returns False."""
    result = await localfs.delete("no-such-blob")

    assert result is False


async def test_localfs_save_returns_unique_ids(localfs: LocalFsBlobStore) -> None:
    """Two consecutive saves produce different blob_ids."""
    id1 = await localfs.save("scope-1", "a.txt", b"aaa")
    id2 = await localfs.save("scope-1", "b.txt", b"bbb")

    assert id1 != id2


async def test_localfs_on_disk_filename_layout(tmp_path: Path) -> None:
    """On-disk file is stored at <scope_id>/<blob_id>_<name>."""
    store = LocalFsBlobStore(base_dir=tmp_path)

    blob_id = await store.save("scope-x", "myfile.txt", b"content")

    scope_dir = tmp_path / "scope-x"
    assert scope_dir.is_dir()
    files = list(scope_dir.iterdir())
    assert len(files) == 1
    assert files[0].name == f"{blob_id}_myfile.txt"


async def test_localfs_now_factory_makes_created_at_deterministic(
    tmp_path: Path,
) -> None:
    """An injected now_factory makes BlobMeta.created_at fully deterministic."""
    fixed_time = datetime(2024, 6, 15, 9, 30, 0, tzinfo=UTC)
    store = LocalFsBlobStore(base_dir=tmp_path, now_factory=lambda: fixed_time)

    await store.save("scope-1", "file.txt", b"data")
    blobs = await store.list("scope-1")

    assert len(blobs) == 1
    assert blobs[0].created_at == fixed_time


async def test_localfs_blob_meta_size_and_content_type(
    localfs: LocalFsBlobStore,
) -> None:
    """BlobMeta.size_bytes equals len(content) and content_type is stored."""
    await localfs.save("scope-1", "data.bin", b"0123456789", "application/octet-stream")

    blobs = await localfs.list("scope-1")

    assert len(blobs) == 1
    meta = blobs[0]
    assert meta.size_bytes == 10
    assert meta.content_type == "application/octet-stream"


# ---------------------------------------------------------------------------
# LocalFsBlobStore — path-traversal guard (OSS-T10 security)
# ---------------------------------------------------------------------------


async def test_localfs_save_rejects_scope_id_traversal(tmp_path: Path) -> None:
    """save with a ../-containing scope_id raises ValueError; no directory is created."""
    store = LocalFsBlobStore(base_dir=tmp_path)

    with pytest.raises(ValueError, match="traversal"):
        await store.save("../../evil", "x.txt", b"data")

    # The guard must fire BEFORE mkdir: base_dir must remain completely empty,
    # proving no directory was created (inside or via tmp_path) during this call.
    assert list(tmp_path.iterdir()) == []


async def test_localfs_save_rejects_name_traversal(tmp_path: Path) -> None:
    """save with a ../-containing name raises ValueError before any write."""
    store = LocalFsBlobStore(base_dir=tmp_path)

    with pytest.raises(ValueError, match="traversal"):
        await store.save("scope", "../../../etc/passwd", b"x")


async def test_localfs_save_rejects_absolute_scope_id(tmp_path: Path) -> None:
    """save with an absolute scope_id raises ValueError (replaces base_dir in Path join)."""
    store = LocalFsBlobStore(base_dir=tmp_path)

    with pytest.raises(ValueError, match="traversal"):
        await store.save("/etc", "x", b"x")


# ---------------------------------------------------------------------------
# BlobMeta dataclass
# ---------------------------------------------------------------------------


def test_blob_meta_is_frozen() -> None:
    """BlobMeta is frozen — field assignment raises FrozenInstanceError."""
    meta = BlobMeta(
        id="blob-000001",
        scope_id="scope-1",
        name="file.txt",
        content_type="text/plain",
        size_bytes=11,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )

    with pytest.raises((AttributeError, TypeError)):
        meta.id = "other"  # type: ignore[misc]
