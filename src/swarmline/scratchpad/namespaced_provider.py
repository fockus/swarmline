"""NamespacedScratchpadProvider — isolates one tenant/session inside a shared backend.

A scratchpad provider is usually built once and shared by every run in the
process, while entry keys come straight from the model. Two callers writing
``"plan"`` therefore land in the same slot: one reads the other's note,
overwrites it, deletes it, and ``read(None)`` enumerates everything in the
process. Where those callers are different tenants, that is a data leak.

This decorator makes a shared backend safe without teaching it about tenants:
every key is prefixed with ``namespace`` on the way in, and every read/list/
search/delete is filtered back to that prefix on the way out. The namespace is
an opaque string — this module knows nothing about tenants, workspaces, or any
particular application's identity model.

Keys stay the model's own: the prefix is added and stripped at the boundary, so
an agent that wrote ``"plan"`` reads back an entry whose key is ``"plan"``.
"""

from __future__ import annotations

from swarmline.scratchpad._keys import decode_key, encode_key
from swarmline.scratchpad.protocols import ScratchpadProvider
from swarmline.scratchpad.types import ScratchpadEntry

__all__ = ["NamespacedScratchpadProvider"]

_SEPARATOR = "/"


class NamespacedScratchpadProvider:
    """Scope a `ScratchpadProvider` to a namespace by prefixing entry keys.

    Args:
        base: the shared provider to delegate to.
        namespace: opaque isolation key, e.g. ``"tenant-a/ws-1"``. Normalized to
            end with ``/`` so ``"tenant-a"`` cannot match ``"tenant-abc"``.
    """

    def __init__(self, base: ScratchpadProvider, namespace: str) -> None:
        if not namespace or not namespace.strip().strip(_SEPARATOR):
            raise ValueError("namespace must be a non-empty, non-blank string")
        self._base = base
        self._prefix = namespace.strip(_SEPARATOR) + _SEPARATOR

    @property
    def namespace(self) -> str:
        return self._prefix

    def _scoped(self, key: str) -> str:
        # The key is MODEL-CONTROLLED, so it is encoded into a single opaque
        # segment before concatenation. Raw concatenation is ambiguous:
        # `ns="a"` + `key="b/plan"` and `ns="a/b"` + `key="plan"` both yield
        # `a/b/plan`, letting one namespace address another's entries.
        return f"{self._prefix}{encode_key(key)}"

    def _owns(self, key: str) -> bool:
        """Whether `key` belongs to THIS namespace and not a nested one.

        The remainder must be a single encoded segment: `a/b/plan` stored by
        namespace `a/b` must not be claimed by namespace `a`, which would
        otherwise see it as key `b/plan`.
        """
        if not key.startswith(self._prefix):
            return False
        remainder = key[len(self._prefix) :]
        # `bool(remainder)` matters: the prefix itself is the CONTAINER, not an
        # entry inside it. An empty remainder trivially contains no separator, so
        # without this check the namespace would claim its own prefix and surface
        # a phantom entry whose key decodes to "".
        return bool(remainder) and _SEPARATOR not in remainder

    def _unscoped(self, entry: ScratchpadEntry) -> ScratchpadEntry:
        """Return the entry as the caller spelled it — without the prefix."""
        return ScratchpadEntry(
            key=decode_key(entry.key[len(self._prefix) :]),
            content=entry.content,
            tags=entry.tags,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    async def write(
        self, key: str, content: str, tags: tuple[str, ...] = ()
    ) -> ScratchpadEntry:
        stored = await self._base.write(self._scoped(key), content, tags)
        return self._unscoped(stored) if self._owns(stored.key) else stored

    async def read(
        self, key: str | None
    ) -> list[ScratchpadEntry] | ScratchpadEntry | None:
        if key is None:
            entries = await self._base.read(None)
            if not isinstance(entries, list):
                return []
            return [self._unscoped(entry) for entry in entries if self._owns(entry.key)]
        entry = await self._base.read(self._scoped(key))
        if entry is None or isinstance(entry, list):
            return None
        return self._unscoped(entry) if self._owns(entry.key) else None

    async def search(self, query: str) -> list[ScratchpadEntry]:
        # Filtering the shared backend's hits is what keeps CONTENT search from
        # crossing the namespace: prefixing keys alone would still let a query
        # match another namespace's body text.
        results = await self._base.search(query)
        return [self._unscoped(entry) for entry in results if self._owns(entry.key)]

    async def delete(self, key: str) -> bool:
        return await self._base.delete(self._scoped(key))


def _check_protocol_conformance() -> None:
    """Compile-time assertion that the decorator still satisfies the port."""
    from swarmline.scratchpad.inmemory_provider import InMemoryScratchpadProvider

    _: ScratchpadProvider = NamespacedScratchpadProvider(
        InMemoryScratchpadProvider(), "ns"
    )
