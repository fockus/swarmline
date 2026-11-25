"""OpenVikingScratchpadProvider — AGFS-backed scratchpad using OpenViking namespace.

Structural Protocol ``OpenVikingAgfsClient`` is what the taskloom adapter satisfies
(same method signatures). No hard dependency on the OpenViking SDK here — just the shape.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from swarmline.scratchpad._keys import decode_key, encode_key
from swarmline.scratchpad.types import ScratchpadEntry


class ScratchpadWriteError(RuntimeError):
    """A scratchpad entry was NOT stored.

    Raised instead of returning a fabricated entry so the failure can reach the
    model as a tool error rather than a false ``status: ok``.
    """

    def __init__(self, key: str, reason: str = "backend rejected the write") -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"scratchpad write failed for key {key!r}: {reason}")


@runtime_checkable
class OpenVikingAgfsClient(Protocol):
    """AGFS client interface that OpenVikingScratchpadProvider delegates to.

    Implementations: taskloom.infrastructure.openviking.agfs_adapter.OpenVikingAgfsAdapter.
    """

    async def write(
        self, uri: str, content: str, metadata: dict[str, Any] | None = None
    ) -> bool: ...

    async def read(self, uri: str) -> dict[str, Any] | None: ...

    async def ls(self, namespace_uri: str) -> list[dict[str, Any]]: ...

    async def search(
        self, query: str, target_uri: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def rm(self, uri: str) -> bool: ...


def _extract_key(uri: str, namespace_uri: str) -> str:
    """Recover the caller's own key from a stored URI (inverse of `_uri`)."""
    prefix = namespace_uri.rstrip("/") + "/"
    if uri.startswith(prefix):
        return decode_key(uri[len(prefix) :])
    return decode_key(uri.rsplit("/", 1)[-1])


def _dict_to_entry(raw: dict[str, Any], *, key: str) -> ScratchpadEntry:
    metadata = raw.get("metadata") or {}
    tags_raw = metadata.get("tags") if isinstance(metadata, dict) else None
    tags: tuple[str, ...] = (
        tuple(tags_raw) if isinstance(tags_raw, (list, tuple)) else ()
    )
    content = str(raw.get("content", ""))
    return ScratchpadEntry(key=key, content=content, tags=tags)


class OpenVikingScratchpadProvider:
    """AGFS-backed scratchpad — maps scratchpad ops to namespaced AGFS URIs."""

    def __init__(self, ov_client: OpenVikingAgfsClient, namespace_uri: str) -> None:
        self._client = ov_client
        self._namespace = namespace_uri.rstrip("/")

    def _uri(self, key: str) -> str:
        # Encoded for the same reason as in NamespacedScratchpadProvider, and
        # more urgently: this address is a URI handed to a path-aware backend,
        # so a raw `../` in a model-supplied key could be normalised out of the
        # tenant-scoped namespace entirely.
        return f"{self._namespace}/{encode_key(key)}"

    def with_namespace(self, namespace_uri: str) -> OpenVikingScratchpadProvider:
        """Return a provider over a different namespace, reusing this client.

        Callers that share one process-wide provider across isolation boundaries
        (tenants, sessions) need a per-boundary namespace. Rebinding here — rather
        than only prefixing keys — also scopes `search`, which passes the
        namespace as `target_uri`: prefixed keys alone would still let a content
        search match another namespace's body text.

        The provider is a thin object over the shared client, so rebuilding it per
        boundary is cheap and opens no new connection.
        """
        return OpenVikingScratchpadProvider(
            ov_client=self._client, namespace_uri=namespace_uri
        )

    async def write(
        self, key: str, content: str, tags: tuple[str, ...] = ()
    ) -> ScratchpadEntry:
        """Store an entry, or raise :class:`ScratchpadWriteError` if it was not stored.

        The returned ``ScratchpadEntry`` used to be constructed unconditionally,
        so a rejected AGFS write still produced a confident "here is your entry".
        ``scratch_write`` then reported ``status: ok`` to the model for data that
        does not exist, and the next ``scratch_read`` came back empty. An agent
        planning around memory it was told it had is worse off than one with no
        scratchpad at all — this path must fail loudly.
        """
        metadata: dict[str, Any] = {"tags": list(tags)}
        stored = await self._client.write(self._uri(key), content, metadata)
        if stored is not True:
            # Fail CLOSED on anything that is not an explicit confirmation. The
            # Protocol declared `-> None` until this contract was tightened, so a
            # client written against the old annotation returns `None` for both
            # success and failure; accepting it would reinstate the silent-success
            # bug for exactly the implementations most likely to still have it.
            raise ScratchpadWriteError(
                key, f"backend returned {stored!r} instead of a confirmed write"
            )
        return ScratchpadEntry(key=key, content=content, tags=tuple(tags))

    async def read(
        self, key: str | None
    ) -> list[ScratchpadEntry] | ScratchpadEntry | None:
        if key is None:
            raw_entries = await self._client.ls(self._namespace)
            return [
                _dict_to_entry(
                    item, key=_extract_key(str(item.get("uri", "")), self._namespace)
                )
                for item in raw_entries
            ]
        raw = await self._client.read(self._uri(key))
        if raw is None:
            return None
        return _dict_to_entry(raw, key=key)

    async def search(self, query: str) -> list[ScratchpadEntry]:
        results = await self._client.search(query, target_uri=self._namespace)
        return [
            _dict_to_entry(
                item, key=_extract_key(str(item.get("uri", "")), self._namespace)
            )
            for item in results
        ]

    async def delete(self, key: str) -> bool:
        return await self._client.rm(self._uri(key))
