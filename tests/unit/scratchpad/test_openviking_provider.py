"""Contract tests for OpenVikingScratchpadProvider — AGFS-backed scratchpad.

Verifies delegation to OpenVikingAgfsClient Protocol + namespace URI mapping.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from swarmline.scratchpad.openviking_provider import (
    OpenVikingAgfsClient,
    OpenVikingScratchpadProvider,
    ScratchpadWriteError,
)
from swarmline.scratchpad.protocols import ScratchpadProvider


@pytest.fixture
def ov_client() -> AsyncMock:
    client = AsyncMock()
    client.write = AsyncMock(
        return_value=True
    )  # Protocol: `-> bool`, True == confirmed stored
    client.read = AsyncMock(return_value=None)
    client.ls = AsyncMock(return_value=[])
    client.search = AsyncMock(return_value=[])
    client.rm = AsyncMock(return_value=True)
    return client


@pytest.fixture
def provider(ov_client: AsyncMock) -> OpenVikingScratchpadProvider:
    return OpenVikingScratchpadProvider(
        ov_client=ov_client, namespace_uri="agfs://scratchpad"
    )


class TestStructuralCompliance:
    def test_implements_scratchpad_provider(
        self, provider: OpenVikingScratchpadProvider
    ) -> None:
        assert isinstance(provider, ScratchpadProvider)

    def test_agfs_client_protocol_checkable(self, ov_client: AsyncMock) -> None:
        assert isinstance(ov_client, OpenVikingAgfsClient)


class TestWrite:
    async def test_write_calls_ov_client_with_namespaced_uri(
        self, provider: OpenVikingScratchpadProvider, ov_client: AsyncMock
    ) -> None:
        await provider.write("notes", "hello")
        assert ov_client.write.await_count == 1
        call_args = ov_client.write.await_args
        uri_arg = call_args.args[0]
        content_arg = call_args.args[1]
        assert uri_arg.endswith("/notes")
        assert uri_arg.startswith("agfs://scratchpad")
        assert content_arg == "hello"

    async def test_write_passes_tags_in_metadata(
        self, provider: OpenVikingScratchpadProvider, ov_client: AsyncMock
    ) -> None:
        await provider.write("notes", "c", tags=("a", "b"))
        call = ov_client.write.await_args
        metadata: dict[str, Any] = call.kwargs.get("metadata") or (
            call.args[2] if len(call.args) > 2 else {}
        )
        assert "tags" in metadata
        assert tuple(metadata["tags"]) == ("a", "b")


class TestRead:
    async def test_read_specific_key_returns_entry_on_hit(
        self, provider: OpenVikingScratchpadProvider, ov_client: AsyncMock
    ) -> None:
        ov_client.read.return_value = {"content": "data", "metadata": {"tags": ["x"]}}
        entry = await provider.read("notes")
        assert entry is not None and not isinstance(entry, list)
        assert entry.key == "notes"
        assert entry.content == "data"
        assert entry.tags == ("x",)

    async def test_read_missing_key_returns_none(
        self, provider: OpenVikingScratchpadProvider, ov_client: AsyncMock
    ) -> None:
        ov_client.read.return_value = None
        assert await provider.read("missing") is None

    async def test_read_none_lists_namespace(
        self, provider: OpenVikingScratchpadProvider, ov_client: AsyncMock
    ) -> None:
        ov_client.ls.return_value = [
            {"uri": "agfs://scratchpad/a", "content": "1"},
            {"uri": "agfs://scratchpad/b", "content": "2"},
        ]
        entries = await provider.read(None)
        assert isinstance(entries, list)
        assert {e.key for e in entries} == {"a", "b"}


class TestSearch:
    async def test_search_delegates_and_maps_results(
        self, provider: OpenVikingScratchpadProvider, ov_client: AsyncMock
    ) -> None:
        ov_client.search.return_value = [
            {"uri": "agfs://scratchpad/k1", "content": "hit"}
        ]
        results = await provider.search("hit")
        assert [e.key for e in results] == ["k1"]
        ov_client.search.assert_awaited_once()


class TestDelete:
    async def test_delete_delegates_to_rm(
        self, provider: OpenVikingScratchpadProvider, ov_client: AsyncMock
    ) -> None:
        assert await provider.delete("notes") is True
        ov_client.rm.assert_awaited_once()
        uri_arg = ov_client.rm.await_args.args[0]
        assert uri_arg == "agfs://scratchpad/notes"


class TestWriteFailureIsNotReportedAsSuccess:
    """The provider must never hand back an entry it did not store.

    `write` used to build a `ScratchpadEntry` unconditionally, so a rejected AGFS
    write still looked like a stored note. `scratch_write` then told the model
    `status: ok` for data that does not exist, and the next `scratch_read` came
    back empty — the agent plans against memory it was told it had.
    """

    async def test_write_raises_when_the_client_reports_failure(
        self, ov_client: AsyncMock
    ) -> None:
        ov_client.write = AsyncMock(return_value=False)
        provider = OpenVikingScratchpadProvider(
            ov_client=ov_client, namespace_uri="agfs://scratchpad"
        )

        with pytest.raises(ScratchpadWriteError) as failure:
            await provider.write("notes", "content that never lands")

        assert failure.value.key == "notes"

    async def test_write_raises_when_the_client_returns_none(
        self, ov_client: AsyncMock
    ) -> None:
        """`None` is NOT a confirmed write.

        The Protocol declared `-> None` before this contract was tightened, so a
        client written against the old annotation returns `None` on every call —
        success and failure alike. Treating that as success reinstates exactly the
        silent-success bug, so an unconfirmed write must fail closed.
        """
        ov_client.write = AsyncMock(return_value=None)
        provider = OpenVikingScratchpadProvider(
            ov_client=ov_client, namespace_uri="agfs://scratchpad"
        )

        with pytest.raises(ScratchpadWriteError):
            await provider.write("notes", "content with an unconfirmed write")

    async def test_write_returns_the_entry_when_the_client_confirms(
        self, ov_client: AsyncMock
    ) -> None:
        ov_client.write = AsyncMock(return_value=True)
        provider = OpenVikingScratchpadProvider(
            ov_client=ov_client, namespace_uri="agfs://scratchpad"
        )

        entry = await provider.write("notes", "stored for real", tags=("a",))

        assert entry.key == "notes"
        assert entry.content == "stored for real"
        assert entry.tags == ("a",)

    async def test_client_exceptions_propagate_rather_than_becoming_an_entry(
        self, ov_client: AsyncMock
    ) -> None:
        ov_client.write = AsyncMock(side_effect=RuntimeError("backend down"))
        provider = OpenVikingScratchpadProvider(
            ov_client=ov_client, namespace_uri="agfs://scratchpad"
        )

        with pytest.raises(RuntimeError, match="backend down"):
            await provider.write("notes", "content")
