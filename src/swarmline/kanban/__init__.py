"""Kanban module — opt-in, hermes-semantics recursive multi-parent board.

Not imported by the swarmline core; the core runtime stays byte-identical
when this module is never registered (REQ-ORC-014).

Re-exports domain types + storage protocols + reference adapters + the
opt-in tools factories + the briefing renderer:
    from swarmline.kanban import (
        KanbanTask, KanbanStatus, BlockKind, TaskLink, KanbanNote,
        KanbanStore, KanbanReadiness, KanbanAssignment, KanbanRetitle,
        KanbanDispatch, KanbanNotes,
        InMemoryKanbanStore, SqliteKanbanStore,
        BriefingCaps, render_worker_context,
        create_kanban_tools, create_kanban_liveness_tools, create_kanban_note_tools,
    )
"""

from __future__ import annotations

from swarmline.kanban.briefing import BriefingCaps, render_worker_context
from swarmline.kanban.inmemory import InMemoryKanbanStore
from swarmline.kanban.sqlite import SqliteKanbanStore
from swarmline.kanban.store import (
    KanbanAssignment,
    KanbanDispatch,
    KanbanNotes,
    KanbanReadiness,
    KanbanRetitle,
    KanbanStore,
)
from swarmline.kanban.tools import (
    create_kanban_liveness_tools,
    create_kanban_note_tools,
    create_kanban_tools,
)
from swarmline.kanban.types import (
    BlockKind,
    KanbanNote,
    KanbanStatus,
    KanbanTask,
    TaskLink,
)

__all__ = [
    "BlockKind",
    "BriefingCaps",
    "InMemoryKanbanStore",
    "KanbanAssignment",
    "KanbanDispatch",
    "KanbanNote",
    "KanbanNotes",
    "KanbanReadiness",
    "KanbanRetitle",
    "KanbanStatus",
    "KanbanStore",
    "KanbanTask",
    "SqliteKanbanStore",
    "TaskLink",
    "create_kanban_liveness_tools",
    "create_kanban_note_tools",
    "create_kanban_tools",
    "render_worker_context",
]
