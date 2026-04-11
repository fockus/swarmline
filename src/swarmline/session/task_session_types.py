"""Domain types for task-bound session state."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskSessionParams:
    """Session parameters bound to a specific (agent_id, task_id) pair.

    Allows agents to resume conversations on specific tasks after restart.
    """

    agent_id: str
    task_id: str
    params: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
