"""Reference-based conversation history for the Temporal runtime.

Temporal caps payloads (~2 MB) and workflow history (~50 MB). With inline
history every LLM step input carries the entire growing conversation, so
long tool-using runs grow the workflow history quadratically. In reference
mode the conversation lives in a worker-side :class:`HistoryStore`; the
workflow carries only a revision number, LLM activities materialize the
messages at call time, and per-turn deltas are appended through the history
activity.

Revisions are message counts. Appends are idempotent under activity
retries: an append whose ``expected_revision`` is behind the store's
current revision is a duplicate delivery and returns the current revision
unchanged.

Stores are worker-side infrastructure. :class:`InMemoryHistoryStore` works
for tests and single-worker setups only — with a worker fleet, every worker
on the task queue must see the same history, so use
:class:`MessageStoreHistoryAdapter` over a shared ``MessageStore``
(Postgres/SQLite) or implement the protocol over your own storage.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

DEFAULT_HISTORY_USER_ID = "swarmline-temporal"


@runtime_checkable
class HistoryStore(Protocol):
    """Port: per-run conversation history keyed by ``run_id``."""

    async def append(
        self,
        run_id: str,
        messages: list[dict[str, Any]],
        expected_revision: int = -1,
    ) -> int:
        """Append messages; return the new revision (total message count).

        When ``expected_revision >= 0`` and the store has already advanced
        past it, the call is a duplicate (activity retry) — do not append,
        return the current revision.
        """
        ...

    async def load(self, run_id: str) -> list[dict[str, Any]]:
        """The run's full message list, oldest first."""
        ...


class InMemoryHistoryStore:
    """Dict-backed store — tests and single-worker development only."""

    def __init__(self) -> None:
        self._runs: dict[str, list[dict[str, Any]]] = {}

    async def append(
        self,
        run_id: str,
        messages: list[dict[str, Any]],
        expected_revision: int = -1,
    ) -> int:
        current = self._runs.setdefault(run_id, [])
        if 0 <= expected_revision < len(current):
            return len(current)  # duplicate delivery (activity retry)
        current.extend(dict(m) for m in messages)
        return len(current)

    async def load(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(m) for m in self._runs.get(run_id, [])]


class MessageStoreHistoryAdapter:
    """Bridges a swarmline ``MessageStore`` (Postgres/SQLite/JSONL) to the
    :class:`HistoryStore` port — ``topic_id`` is the run id.
    """

    def __init__(
        self,
        message_store: Any,
        *,
        user_id: str = DEFAULT_HISTORY_USER_ID,
        load_limit: int = 10_000,
    ) -> None:
        self._store = message_store
        self._user_id = user_id
        self._load_limit = load_limit

    async def append(
        self,
        run_id: str,
        messages: list[dict[str, Any]],
        expected_revision: int = -1,
    ) -> int:
        count = await self._store.count_messages(self._user_id, run_id)
        if 0 <= expected_revision < count:
            return count  # duplicate delivery (activity retry)
        for message in messages:
            await self._store.save_message(
                self._user_id,
                run_id,
                message.get("role", ""),
                message.get("content", ""),
                message.get("tool_calls"),
                name=message.get("name"),
                metadata=message.get("metadata"),
            )
        return count + len(messages)

    async def load(self, run_id: str) -> list[dict[str, Any]]:
        records = await self._store.get_messages(
            self._user_id, run_id, limit=self._load_limit
        )
        loaded: list[dict[str, Any]] = []
        for record in records:
            message: dict[str, Any] = {
                "role": record.role,
                "content": record.content,
            }
            if record.name is not None:
                message["name"] = record.name
            if record.tool_calls is not None:
                message["tool_calls"] = record.tool_calls
            if record.metadata is not None:
                message["metadata"] = record.metadata
            loaded.append(message)
        return loaded
