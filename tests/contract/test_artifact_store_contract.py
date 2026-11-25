"""Contract tests for ``ArtifactStorePort`` -- shared across all implementations.

Any implementation added here must pass every scenario below. Only
``FSArtifactStore`` exists today; S3/other backends are deferred (see
``swarmline/artifacts/protocols.py``).
"""

from __future__ import annotations

import pytest
from swarmline.artifacts.fs_store import FSArtifactStore
from swarmline.artifacts.protocols import ArtifactStorePort

pytestmark = pytest.mark.asyncio


@pytest.fixture(params=["fs"])
def store(request, tmp_path):
    if request.param == "fs":
        return FSArtifactStore(base_path=tmp_path / "artifacts")
    raise ValueError(f"Unknown store param: {request.param}")  # pragma: no cover


class TestProtocolShape:
    def test_fs_artifact_store_satisfies_protocol(self, tmp_path) -> None:
        assert isinstance(FSArtifactStore(base_path=tmp_path), ArtifactStorePort)


class TestSaveLoadRoundtrip:
    async def test_save_then_load_returns_original_bytes(self, store) -> None:
        artifact = await store.save(
            "task-1", b"hello world", "report.txt", "text/plain"
        )

        loaded = await store.load(artifact)

        assert loaded == b"hello world"

    async def test_save_returns_artifact_with_metadata(self, store) -> None:
        artifact = await store.save("task-1", b"content", "notes.md", "text/markdown")

        assert artifact.id
        assert artifact.title == "notes.md"
        assert artifact.mime_type == "text/markdown"
        assert artifact.size_bytes == len(b"content")

    async def test_save_twice_produces_distinct_artifact_ids(self, store) -> None:
        first = await store.save("task-1", b"a", "a.txt", "text/plain")
        second = await store.save("task-1", b"b", "b.txt", "text/plain")

        assert first.id != second.id

    async def test_load_missing_artifact_raises_file_not_found(self, store) -> None:
        artifact = await store.save("task-1", b"x", "x.txt", "text/plain")
        artifact.path.unlink()

        with pytest.raises(FileNotFoundError):
            await store.load(artifact)

    async def test_save_isolates_by_task_id(self, store) -> None:
        a = await store.save("task-a", b"a-content", "same.txt", "text/plain")
        b = await store.save("task-b", b"b-content", "same.txt", "text/plain")

        assert await store.load(a) == b"a-content"
        assert await store.load(b) == b"b-content"
