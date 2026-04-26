"""Goal queue for persistent agent graphs — FIFO queue with status tracking."""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any


class GoalStatus(str, Enum):
    """Status of a goal in the queue."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class GoalEntry:
    """Immutable record of a goal in the queue."""

    id: str
    goal: str
    status: GoalStatus = GoalStatus.QUEUED
    submitted_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class GoalQueue:
    """In-memory FIFO goal queue with status tracking."""

    def __init__(self) -> None:
        self._queue: deque[str] = deque()  # goal IDs in FIFO order
        self._goals: dict[str, GoalEntry] = {}

    def submit(self, goal: str, *, metadata: dict[str, Any] | None = None) -> GoalEntry:
        """Submit a new goal. Returns the created GoalEntry."""
        entry = GoalEntry(
            id=f"goal-{uuid.uuid4().hex[:8]}",
            goal=goal,
            metadata=metadata or {},
        )
        self._goals[entry.id] = entry
        self._queue.append(entry.id)
        return entry

    def peek(self) -> GoalEntry | None:
        """Peek at the next goal without removing it."""
        while self._queue:
            gid = self._queue[0]
            entry = self._goals.get(gid)
            if entry and entry.status == GoalStatus.QUEUED:
                return entry
            self._queue.popleft()  # skip completed/failed
        return None

    def dequeue(self) -> GoalEntry | None:
        """Dequeue the next QUEUED goal, marking it RUNNING."""
        entry = self.peek()
        if entry is None:
            return None
        self._queue.popleft()
        updated = replace(entry, status=GoalStatus.RUNNING)
        self._goals[entry.id] = updated
        return updated

    def mark_complete(self, goal_id: str, run_id: str | None = None) -> None:
        """Mark a goal as completed."""
        entry = self._goals.get(goal_id)
        if entry is None:
            raise KeyError(f"Goal '{goal_id}' not found")
        self._goals[goal_id] = replace(
            entry,
            status=GoalStatus.COMPLETED,
            completed_at=time.time(),
            run_id=run_id,
        )

    def mark_failed(self, goal_id: str, run_id: str | None = None) -> None:
        """Mark a goal as failed."""
        entry = self._goals.get(goal_id)
        if entry is None:
            raise KeyError(f"Goal '{goal_id}' not found")
        self._goals[goal_id] = replace(
            entry,
            status=GoalStatus.FAILED,
            completed_at=time.time(),
            run_id=run_id,
        )

    def list_all(self) -> list[GoalEntry]:
        """List all goals (all statuses)."""
        return list(self._goals.values())

    def list_pending(self) -> list[GoalEntry]:
        """List goals that are QUEUED."""
        return [g for g in self._goals.values() if g.status == GoalStatus.QUEUED]

    @property
    def size(self) -> int:
        """Number of QUEUED goals."""
        return sum(1 for g in self._goals.values() if g.status == GoalStatus.QUEUED)
