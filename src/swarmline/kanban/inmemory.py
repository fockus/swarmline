"""In-memory kanban store — dict-backed reference adapter (opt-in module).

Mirrors `multi_agent/graph_task_board.py`'s idiom (async lock, frozen
dataclass round-tripping via `dataclasses.replace`) adapted for the
multi-parent `task_links` relation instead of a single `parent_task_id`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from swarmline.kanban._time import canonical_iso
from swarmline.kanban._time import now_iso as _now_iso
from swarmline.kanban.store import _BLOCK_ESCALATION_THRESHOLD
from swarmline.kanban.types import BlockKind, KanbanNote, KanbanStatus, KanbanTask


# ponytail: SQLite round-trips through JSON on every read, so callers there
# never see the store's own object. Copy metadata here too, so mutating a
# returned task can never corrupt the stored one (KanbanTask is frozen but
# `metadata` is a mutable dict — this is the one field that can leak).
def _copy(task: KanbanTask) -> KanbanTask:
    return replace(task, metadata=dict(task.metadata))


class InMemoryKanbanStore:
    """Dict-backed implementation of `KanbanStore` + `KanbanReadiness`."""

    def __init__(self) -> None:
        self._tasks: dict[str, KanbanTask] = {}
        self._children: dict[str, set[str]] = {}  # parent_id -> child ids
        self._lock = asyncio.Lock()

    # --- KanbanStore ---

    async def create_task(self, task: KanbanTask) -> None:
        async with self._lock:
            if task.id in self._tasks:
                raise ValueError(f"Task already exists: {task.id!r}")
            self._tasks[task.id] = _copy(task)
            self._children.setdefault(task.id, set())
            for parent_id in task.parent_ids:
                self._children.setdefault(parent_id, set()).add(task.id)

    async def link_tasks(self, parent_id: str, child_id: str) -> None:
        async with self._lock:
            if parent_id not in self._tasks:
                raise ValueError(f"Unknown parent task: {parent_id!r}")
            if child_id not in self._tasks:
                raise ValueError(f"Unknown child task: {child_id!r}")
            if self._would_create_cycle(parent_id, child_id):
                raise ValueError(
                    f"Linking {parent_id!r} -> {child_id!r} would create a cycle"
                )
            child = self._tasks[child_id]
            if parent_id not in child.parent_ids:
                self._tasks[child_id] = replace(
                    child, parent_ids=(*child.parent_ids, parent_id)
                )
            self._children.setdefault(parent_id, set()).add(child_id)

    async def set_status(
        self,
        task_id: str,
        status: KanbanStatus,
        *,
        block_kind: BlockKind | None = None,
    ) -> KanbanTask:
        async with self._lock:
            task = self._require(task_id)
            updated = _apply_status(task, status, block_kind)
            self._tasks[task_id] = updated
            return _copy(updated)

    async def list_tasks(self, **filters: Any) -> list[KanbanTask]:
        async with self._lock:
            result = list(self._tasks.values())
        if "status" in filters:
            result = [t for t in result if t.status == filters["status"]]
        return [_copy(t) for t in result]

    async def get_subtree(self, task_id: str) -> list[KanbanTask]:
        async with self._lock:
            return self._collect_subtree(task_id)

    # --- KanbanReadiness ---

    async def recompute_ready(self, task_id: str) -> list[str]:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return []
            children = [
                self._tasks[c]
                for c in self._children.get(task_id, set())
                if c in self._tasks
            ]
            if not children or not all(c.status == KanbanStatus.DONE for c in children):
                return []
            if task.status in (KanbanStatus.READY, KanbanStatus.DONE):
                return []
            self._tasks[task_id] = replace(task, status=KanbanStatus.READY)
            return [task_id]

    # --- KanbanAssignment ---

    async def claim_task(self, task_id: str, assignee: str) -> KanbanTask:
        async with self._lock:
            task = self._require(task_id)
            now = _now_iso()
            updated = replace(
                task, assignee=assignee, claimed_at=now, last_heartbeat_at=now
            )
            self._tasks[task_id] = updated
            return _copy(updated)

    async def heartbeat(self, task_id: str) -> KanbanTask:
        async with self._lock:
            task = self._require(task_id)
            if task.assignee is None:
                raise ValueError(f"Task {task_id!r} has never been claimed")
            updated = replace(task, last_heartbeat_at=_now_iso())
            self._tasks[task_id] = updated
            return _copy(updated)

    # --- KanbanRetitle ---

    async def update_title(self, task_id: str, title: str) -> KanbanTask:
        async with self._lock:
            task = self._require(task_id)
            updated = replace(task, title=title)
            self._tasks[task_id] = updated
            return _copy(updated)

    # --- KanbanDispatch ---

    async def try_claim(
        self,
        task_id: str,
        assignee: str,
        *,
        lease_id: str,
        stale_before: str,
    ) -> KanbanTask | None:
        stale_before = canonical_iso(stale_before)
        async with self._lock:
            task = self._require(task_id)
            if not _is_claimable(task, stale_before):
                return None
            now = _now_iso()
            metadata = dict(task.metadata)
            metadata["lease_id"] = lease_id
            metadata["dispatched"] = True
            updated = replace(
                task,
                assignee=assignee,
                claimed_at=now,
                last_heartbeat_at=now,
                metadata=metadata,
            )
            self._tasks[task_id] = updated
            return _copy(updated)

    async def release_claim(self, task_id: str, *, lease_id: str) -> KanbanTask:
        async with self._lock:
            task = self._require(task_id)
            if task.metadata.get("lease_id") != lease_id:
                return _copy(task)
            metadata = dict(task.metadata)
            metadata.pop("lease_id", None)
            updated = replace(task, metadata=metadata)
            self._tasks[task_id] = updated
            return _copy(updated)

    async def list_claimable(
        self,
        *,
        statuses: Sequence[KanbanStatus],
        stale_before: str,
        limit: int,
        include_fresh_claims: bool = False,
    ) -> list[KanbanTask]:
        stale_before = canonical_iso(stale_before)
        async with self._lock:
            result: list[KanbanTask] = []
            for task in self._tasks.values():
                if self._children.get(task.id):
                    continue  # has children — not a leaf
                if task.status not in statuses:
                    continue
                if not include_fresh_claims and not _is_claimable(task, stale_before):
                    continue
                result.append(task)
                if len(result) >= limit:
                    break
            return [_copy(t) for t in result]

    # --- KanbanNotes ---

    async def append_note(
        self,
        task_id: str,
        note: KanbanNote,
        *,
        max_notes: int,
    ) -> KanbanTask:
        async with self._lock:
            task = self._require(task_id)
            notes = list(task.metadata.get("notes", []))
            notes.append(_note_to_dict(note))
            metadata = dict(task.metadata)
            metadata["notes"] = notes[-max_notes:]
            updated = replace(task, metadata=metadata)
            self._tasks[task_id] = updated
            return _copy(updated)

    # --- Convenience (not part of the KanbanStore protocol, ISP <=5) ---

    async def complete_task(self, task_id: str) -> KanbanTask:
        """Sugar for `set_status(task_id, KanbanStatus.DONE)`."""
        return await self.set_status(task_id, KanbanStatus.DONE)

    # --- Internal ---

    def _require(self, task_id: str) -> KanbanTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Unknown task: {task_id!r}")
        return task

    def _would_create_cycle(self, parent_id: str, child_id: str) -> bool:
        if parent_id == child_id:
            return True
        visited: set[str] = set()
        stack = [parent_id]
        while stack:
            current = stack.pop()
            if current == child_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            current_task = self._tasks.get(current)
            if current_task is None:
                continue
            stack.extend(current_task.parent_ids)
        return False

    def _collect_subtree(self, task_id: str) -> list[KanbanTask]:
        result: list[KanbanTask] = []
        visited: set[str] = set()
        queue = list(self._children.get(task_id, set()))
        while queue:
            child_id = queue.pop(0)
            if child_id in visited:
                continue
            visited.add(child_id)
            child = self._tasks.get(child_id)
            if child is None:
                continue
            result.append(_copy(child))
            queue.extend(self._children.get(child_id, set()))
        return result


def _apply_status(
    task: KanbanTask, status: KanbanStatus, block_kind: BlockKind | None
) -> KanbanTask:
    """Replace `task` with `status` applied, escalating a repeat block to `triage`."""
    if status != KanbanStatus.BLOCKED:
        return replace(task, status=status)
    recurrences = task.block_recurrences + 1
    escalate = recurrences > _BLOCK_ESCALATION_THRESHOLD
    return replace(
        task,
        status=KanbanStatus.TRIAGE if escalate else KanbanStatus.BLOCKED,
        block_kind=block_kind,
        block_recurrences=recurrences,
    )


def _is_claimable(task: KanbanTask, stale_before: str) -> bool:
    """A card is claimable if it has no active lease, or its lease is stale.

    `last_heartbeat_at`/`stale_before` are fixed-format ISO-8601 UTC strings
    (`_now_iso()`), so lexicographic comparison is a valid staleness check.
    """
    if task.metadata.get("lease_id") is None:
        return True
    heartbeat = task.last_heartbeat_at
    return heartbeat is not None and heartbeat < stale_before


def _note_to_dict(note: KanbanNote) -> dict[str, Any]:
    """Serialize `note` to a JSON-plain dict for `metadata['notes']`."""
    return {
        "kind": note.kind,
        "text": note.text,
        "at": note.at,
        "run_id": note.run_id,
        "outcome": note.outcome,
    }
