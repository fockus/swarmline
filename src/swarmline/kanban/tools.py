"""Opt-in kanban tools — create/link/complete/block/show/list.

`create_kanban_tools` follows the exact same opt-in factory idiom as
`orchestration/plan_tools.py::create_plan_tools`: it is composed explicitly
by a caller that wants kanban tools wired into an agent's toolset and is
never imported by the swarmline core (REQ-ORC-014). It returns exactly the
six minimum tools required by REQ-ORC-012 — no more, no less.

Each executor round-trips through the injected `KanbanStore` (+
`KanbanReadiness`) and returns `json.dumps(...)` of a result/error dict,
mirroring `create_plan_tools`'s error handling: `{"status": "error",
"message": ...}` on failure, never an unhandled exception.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from swarmline.kanban.briefing import BriefingCaps
from swarmline.kanban.store import (
    KanbanAssignment,
    KanbanNotes,
    KanbanReadiness,
    KanbanStore,
)
from swarmline.kanban.types import BlockKind, KanbanNote, KanbanStatus, KanbanTask
from swarmline.kanban._time import now_iso as _now_iso
from swarmline.runtime.types import ToolSpec

# Shared with `kanban.briefing.render_worker_context`'s progress-notes cap
# (DRY: one dataclass holds every kanban size cap) — a note the tool appends
# here is exactly as much of the journal as the briefing will later show.
_MAX_NOTES = BriefingCaps().max_notes


class _KanbanBoard(KanbanStore, KanbanReadiness, Protocol):
    """Structural type: a `KanbanStore` that also satisfies `KanbanReadiness`.

    Both InMemory and SQLite reference adapters implement both protocols by
    duck typing, so any real store passed to `create_kanban_tools` already
    satisfies this combined shape.
    """


class _KanbanLiveBoard(KanbanAssignment, Protocol):
    """Structural type: a store that satisfies `KanbanAssignment` (claim + heartbeat).

    Both InMemory and SQLite reference adapters implement it by duck typing,
    same as `_KanbanBoard` above.
    """


# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

_CREATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Уникальный идентификатор карточки."},
        "title": {"type": "string", "description": "Короткое название карточки."},
        "parent_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "ID родительских карточек (multi-parent task_links).",
            "default": [],
        },
        "metadata": {
            "type": "object",
            "description": "Произвольные метаданные карточки.",
            "default": {},
        },
    },
    "required": ["id", "title"],
}

_LINK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "parent_id": {"type": "string", "description": "ID родительской карточки."},
        "child_id": {"type": "string", "description": "ID дочерней карточки."},
    },
    "required": ["parent_id", "child_id"],
}

_COMPLETE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "ID карточки для завершения."},
    },
    "required": ["task_id"],
}

_BLOCK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "ID карточки, которую нужно заблокировать.",
        },
        "block_kind": {
            "type": "string",
            "enum": [kind.value for kind in BlockKind],
            "description": "Типизированная причина блокировки.",
        },
    },
    "required": ["task_id", "block_kind"],
}

_SHOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string", "description": "ID карточки для отображения."},
    },
    "required": ["task_id"],
}

_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [status.value for status in KanbanStatus],
            "description": "Фильтр по статусу (опционально).",
        },
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task_to_dict(task: KanbanTask) -> dict[str, Any]:
    """Serialize a `KanbanTask` to a JSON-safe dict for tool responses.

    `assignee`/`claimed_at`/`last_heartbeat_at` are OMITTED entirely (not
    emitted as `null`) when unset — Sprint J fix-cycle 1 (codex round 1,
    m-6): the six pre-existing tools' response shape for a never-claimed
    task must stay byte-identical to what it was before those three fields
    existed on `KanbanTask`. They only appear once a card has actually been
    claimed (`KanbanAssignment.claim_task`).
    """
    result: dict[str, Any] = {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
        "parent_ids": list(task.parent_ids),
        "block_kind": task.block_kind.value if task.block_kind is not None else None,
        "block_recurrences": task.block_recurrences,
        "metadata": dict(task.metadata),
    }
    if task.assignee is not None:
        result["assignee"] = task.assignee
    if task.claimed_at is not None:
        result["claimed_at"] = task.claimed_at
    if task.last_heartbeat_at is not None:
        result["last_heartbeat_at"] = task.last_heartbeat_at
    return result


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_kanban_tools(
    store: _KanbanBoard,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Create the six opt-in kanban tools bound to `store`."""

    async def kanban_create(args: dict) -> str:
        """Create a kanban card."""
        task_id = args.get("id", "")
        title = args.get("title", "")
        if not task_id or not title:
            return json.dumps({"status": "error", "message": "id и title обязательны"})
        try:
            parent_ids = tuple(args.get("parent_ids") or ())
            metadata = dict(args.get("metadata") or {})
            task = KanbanTask(
                id=task_id, title=title, parent_ids=parent_ids, metadata=metadata
            )
            await store.create_task(task)
            return json.dumps({"status": "ok", "task": _task_to_dict(task)})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def kanban_link(args: dict) -> str:
        """Link a child card under a parent card (multi-parent task_links)."""
        parent_id = args.get("parent_id", "")
        child_id = args.get("child_id", "")
        if not parent_id or not child_id:
            return json.dumps(
                {"status": "error", "message": "parent_id и child_id обязательны"}
            )
        try:
            await store.link_tasks(parent_id, child_id)
            return json.dumps(
                {"status": "ok", "parent_id": parent_id, "child_id": child_id}
            )
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def kanban_complete(args: dict) -> str:
        """Mark a card done and recompute readiness on its parents."""
        task_id = args.get("task_id", "")
        if not task_id:
            return json.dumps({"status": "error", "message": "task_id обязателен"})
        try:
            task = await store.set_status(task_id, KanbanStatus.DONE)
            promoted: list[str] = []
            for parent_id in task.parent_ids:
                promoted.extend(await store.recompute_ready(parent_id))
            return json.dumps(
                {"status": "ok", "task": _task_to_dict(task), "promoted": promoted}
            )
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def kanban_block(args: dict) -> str:
        """Block a card with a typed block_kind."""
        task_id = args.get("task_id", "")
        block_kind_raw = args.get("block_kind", "")
        if not task_id or not block_kind_raw:
            return json.dumps(
                {"status": "error", "message": "task_id и block_kind обязательны"}
            )
        try:
            block_kind = BlockKind(block_kind_raw)
        except ValueError:
            allowed = [kind.value for kind in BlockKind]
            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        f"Некорректный block_kind: {block_kind_raw!r}. "
                        f"Допустимые значения: {allowed}"
                    ),
                }
            )
        try:
            task = await store.set_status(
                task_id, KanbanStatus.BLOCKED, block_kind=block_kind
            )
            return json.dumps({"status": "ok", "task": _task_to_dict(task)})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def kanban_show(args: dict) -> str:
        """Show a single card by id."""
        task_id = args.get("task_id", "")
        if not task_id:
            return json.dumps({"status": "error", "message": "task_id обязателен"})
        try:
            tasks = await store.list_tasks()
            for task in tasks:
                if task.id == task_id:
                    return json.dumps({"status": "ok", "task": _task_to_dict(task)})
            return json.dumps(
                {"status": "error", "message": f"Задача не найдена: {task_id!r}"}
            )
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def kanban_list(args: dict) -> str:
        """List cards, optionally filtered by status."""
        status_raw = args.get("status")
        try:
            filters: dict[str, Any] = {}
            if status_raw:
                filters["status"] = KanbanStatus(status_raw)
            tasks = await store.list_tasks(**filters)
            return json.dumps(
                {"status": "ok", "tasks": [_task_to_dict(t) for t in tasks]}
            )
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    specs = {
        "kanban_create": ToolSpec(
            name="kanban_create",
            description="Создать карточку канбан-борда.",
            parameters=_CREATE_SCHEMA,
        ),
        "kanban_link": ToolSpec(
            name="kanban_link",
            description="Связать дочернюю карточку с родительской (multi-parent).",
            parameters=_LINK_SCHEMA,
        ),
        "kanban_complete": ToolSpec(
            name="kanban_complete",
            description=(
                "Завершить карточку (done) и пересчитать готовность родителей."
            ),
            parameters=_COMPLETE_SCHEMA,
        ),
        "kanban_block": ToolSpec(
            name="kanban_block",
            description="Заблокировать карточку с типизированной причиной блокировки.",
            parameters=_BLOCK_SCHEMA,
        ),
        "kanban_show": ToolSpec(
            name="kanban_show",
            description="Показать одну карточку по id.",
            parameters=_SHOW_SCHEMA,
        ),
        "kanban_list": ToolSpec(
            name="kanban_list",
            description="Показать карточки, опционально отфильтрованные по статусу.",
            parameters=_LIST_SCHEMA,
        ),
    }

    executors: dict[str, Callable] = {
        "kanban_create": kanban_create,
        "kanban_link": kanban_link,
        "kanban_complete": kanban_complete,
        "kanban_block": kanban_block,
        "kanban_show": kanban_show,
        "kanban_list": kanban_list,
    }

    return specs, executors


# ---------------------------------------------------------------------------
# Liveness tools (claim + heartbeat) — Sprint J, AGR-007 (kanban unification)
# ---------------------------------------------------------------------------
#
# A SEPARATE factory from `create_kanban_tools` on purpose: a host application
# may derive an EXACT, frozen toolset contract (e.g. a dispatch-only
# sub-agent's allow-list) from `create_kanban_tools`'s output — growing that
# factory would silently grow any such frozen contract too. These two tools
# are meant to be wired into a DIFFERENT toolset (e.g. the main agent's own
# runtime toolset) than wherever `create_kanban_tools`'s six are wired.

_CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "ID of the card to claim.",
        },
        "assignee": {
            "type": "string",
            "description": "Identifier of the claimant (model/agent name) taking the card.",
        },
    },
    "required": ["task_id", "assignee"],
}

_HEARTBEAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "ID of an already-claimed card.",
        },
    },
    "required": ["task_id"],
}


def create_kanban_liveness_tools(
    store: _KanbanLiveBoard,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Create the two opt-in kanban liveness tools (`kanban_claim`/`kanban_heartbeat`) bound to `store`."""

    async def kanban_claim(args: dict) -> str:
        """Claim a card — records who is working it and stamps initial liveness."""
        task_id = args.get("task_id", "")
        assignee = args.get("assignee", "")
        if not task_id or not assignee:
            return json.dumps(
                {"status": "error", "message": "task_id and assignee are required"}
            )
        try:
            task = await store.claim_task(task_id, assignee)
            return json.dumps({"status": "ok", "task": _task_to_dict(task)})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def kanban_heartbeat(args: dict) -> str:
        """Signal that the claimant is still alive/working on a claimed card."""
        task_id = args.get("task_id", "")
        if not task_id:
            return json.dumps({"status": "error", "message": "task_id is required"})
        try:
            task = await store.heartbeat(task_id)
            return json.dumps({"status": "ok", "task": _task_to_dict(task)})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    specs = {
        "kanban_claim": ToolSpec(
            name="kanban_claim",
            description=(
                "Claim a card: records the claimant (yourself) and a timestamp; does not change the card's status."
            ),
            parameters=_CLAIM_SCHEMA,
        ),
        "kanban_heartbeat": ToolSpec(
            name="kanban_heartbeat",
            description=(
                "Signal liveness on an already-claimed card while working on it for an extended time."
            ),
            parameters=_HEARTBEAT_SCHEMA,
        ),
    }

    executors: dict[str, Callable] = {
        "kanban_claim": kanban_claim,
        "kanban_heartbeat": kanban_heartbeat,
    }

    return specs, executors


# ---------------------------------------------------------------------------
# Progress note tool — Sprint 1a Stage 4 (AGR-012/AGR-017, REQ-LTK-020/021)
# ---------------------------------------------------------------------------
#
# A THIRD, separate factory — same rationale as `create_kanban_liveness_tools`
# above: growing an existing frozen toolset contract silently is worse than a
# host wiring one more explicit factory. `kanban_note` is withheld entirely
# (an empty dict, not a tool that errors at call time) when `store` doesn't
# implement `KanbanNotes` (REQ-LTK-021) — checked once at construction time
# via the runtime-checkable protocol, not per call.

_NOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "ID of the card to leave a progress note on.",
        },
        "text": {
            "type": "string",
            "description": "Progress note body — what you tried, what's still open.",
        },
    },
    "required": ["task_id", "text"],
}


def create_kanban_note_tools(
    store: object,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Create the opt-in `kanban_note` tool bound to `store`, if it supports notes.

    Returns two empty dicts when `store` does not implement `KanbanNotes` —
    the tool is withheld from the agent's toolset rather than exposed and
    failing at call time (REQ-LTK-021).
    """
    if not isinstance(store, KanbanNotes):
        return {}, {}

    async def kanban_note(args: dict) -> str:
        """Leave a progress note on a card, for a future attempt to see."""
        task_id = args.get("task_id", "")
        text = args.get("text", "")
        if not task_id or not text:
            return json.dumps(
                {"status": "error", "message": "task_id and text are required"}
            )
        try:
            note = KanbanNote(kind="progress", text=text, at=_now_iso())
            task = await store.append_note(task_id, note, max_notes=_MAX_NOTES)
            return json.dumps({"status": "ok", "task": _task_to_dict(task)})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    specs = {
        "kanban_note": ToolSpec(
            name="kanban_note",
            description=(
                "Leave a progress note on a card — visible to a future attempt "
                "(yours or another worker's) via its briefing."
            ),
            parameters=_NOTE_SCHEMA,
        ),
    }
    executors: dict[str, Callable] = {"kanban_note": kanban_note}

    return specs, executors
