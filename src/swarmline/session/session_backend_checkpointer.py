"""SessionBackendCheckpointer — adapt a legacy SessionBackend to Checkpointer.

Single-latest adapter (REQ-012/REQ-013): ``SessionBackend`` (save/load/delete
by string key) has no history or lineage -- it overwrites the prior value on
every ``save``. This adapter lets an existing single-latest backend satisfy
the ``Checkpointer`` protocol so it participates without a rewrite, while the
limitation stays explicit: ``list`` returns 0 or 1 entries (never a real
history), ``put`` always overwrites the backend's stored value, and
``parent_id`` is always ``None`` (no fork lineage is possible over a
single-slot store). Callers that need append-only history or fork lineage
should use ``InMemoryCheckpointer`` or ``SqliteCheckpointer`` instead.
"""

from __future__ import annotations

import builtins
import time
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from swarmline.protocols.checkpoint import Checkpoint, CheckpointMeta
from swarmline.session.backends import SessionBackend


class SessionBackendCheckpointer:
    """Adapt a single-latest ``SessionBackend`` to the ``Checkpointer`` port."""

    def __init__(self, backend: SessionBackend) -> None:
        self._backend = backend

    async def put(
        self,
        thread_id: str,
        state: Mapping[str, Any],
        *,
        resource_id: str | None = None,
        parent_id: str | None = None,
        checkpoint_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        cid = checkpoint_id or uuid4().hex
        await self._backend.save(
            thread_id,
            {
                "cid": cid,
                "state": dict(state),
                "resource_id": resource_id,
                "ts": time.time(),
                "metadata": dict(metadata or {}),
            },
        )
        return cid

    async def get(
        self, thread_id: str, *, checkpoint_id: str | None = None
    ) -> Checkpoint | None:
        raw = await self._backend.load(thread_id)
        if raw is None:
            return None
        if checkpoint_id is not None and raw.get("cid") != checkpoint_id:
            return None
        return Checkpoint(
            id=raw["cid"],
            thread_id=thread_id,
            state=raw["state"],
            resource_id=raw.get("resource_id"),
            parent_id=None,
            ts=raw.get("ts", 0.0),
            metadata=raw.get("metadata", {}),
        )

    async def list(self, thread_id: str) -> builtins.list[CheckpointMeta]:
        raw = await self._backend.load(thread_id)
        if raw is None:
            return []
        return [
            CheckpointMeta(
                id=raw["cid"],
                thread_id=thread_id,
                parent_id=None,
                ts=raw.get("ts", 0.0),
                resource_id=raw.get("resource_id"),
                metadata=raw.get("metadata", {}),
            )
        ]

    async def delete(self, thread_id: str, *, checkpoint_id: str | None = None) -> int:
        raw = await self._backend.load(thread_id)
        if raw is None:
            return 0
        if checkpoint_id is not None and raw.get("cid") != checkpoint_id:
            return 0
        return 1 if await self._backend.delete(thread_id) else 0

    async def close(self) -> None:
        """No-op — kept for API parity with durable backends."""
        return None
