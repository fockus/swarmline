"""create_scratchpad_tools — factory producing 4 tools (write/read/search/delete) for a ScratchpadProvider."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from swarmline.domain_types import ToolSpec
from swarmline.scratchpad.protocols import ScratchpadProvider
from swarmline.scratchpad.types import ScratchpadEntry


_WRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "key": {
            "type": "string",
            "description": "Unique key for the scratchpad entry.",
        },
        "content": {
            "type": "string",
            "description": "Entry content (plain text/markdown).",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional tags for filtering/search.",
            "default": [],
        },
    },
    "required": ["key", "content"],
}

_READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "key": {
            "type": "string",
            "description": "Entry key to read. Omit or pass null to list all entries.",
        },
    },
}

_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search phrase (matches key/content/tags).",
        },
    },
    "required": ["query"],
}

_DELETE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "key": {"type": "string", "description": "Entry key to delete."},
    },
    "required": ["key"],
}


def _entry_to_dict(entry: ScratchpadEntry) -> dict[str, Any]:
    raw: dict[str, Any]
    if is_dataclass(entry):
        raw = asdict(entry)  # type: ignore[arg-type]
    else:
        raw = {
            "key": entry.key,
            "content": entry.content,
            "tags": list(getattr(entry, "tags", ())),
        }
    if "tags" in raw:
        raw["tags"] = list(raw["tags"])
    if "created_at" in raw and hasattr(raw["created_at"], "isoformat"):
        raw["created_at"] = raw["created_at"].isoformat()
    if "updated_at" in raw and hasattr(raw["updated_at"], "isoformat"):
        raw["updated_at"] = raw["updated_at"].isoformat()
    return raw


def _make_write(provider: ScratchpadProvider) -> Callable:
    async def executor(key: str, content: str, tags: list[str] | None = None) -> str:
        try:
            entry = await provider.write(key, content, tuple(tags or ()))
        except Exception as exc:
            # A write that did not land must NOT come back as `status: ok`. The
            # model builds its next steps on what it believes it stored, so a
            # false success is strictly worse than an error: it turns a backend
            # outage into a silently wrong plan. Returned as a structured result
            # rather than re-raised so the model can react (retry, or carry the
            # content forward inline) instead of losing the turn.
            return json.dumps(
                {
                    "status": "error",
                    "key": key,
                    "error": f"{type(exc).__name__}: {exc}",
                    "stored": False,
                }
            )
        return json.dumps({"status": "ok", "entry": _entry_to_dict(entry)})

    return executor


def _make_read(provider: ScratchpadProvider) -> Callable:
    async def executor(key: str | None = None) -> str:
        result = await provider.read(key)
        if result is None:
            return json.dumps(None)
        if isinstance(result, list):
            return json.dumps([_entry_to_dict(e) for e in result])
        return json.dumps(_entry_to_dict(result))

    return executor


def _make_search(provider: ScratchpadProvider) -> Callable:
    async def executor(query: str) -> str:
        results = await provider.search(query)
        return json.dumps([_entry_to_dict(e) for e in results])

    return executor


def _make_delete(provider: ScratchpadProvider) -> Callable:
    async def executor(key: str) -> str:
        removed = await provider.delete(key)
        return json.dumps(
            {"status": "ok" if removed else "not_found", "deleted": removed}
        )

    return executor


def create_scratchpad_tools(
    provider: ScratchpadProvider,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Produce the (specs, executors) pair for the 4 scratchpad tools.

    The executors close over ``provider`` and delegate every operation to it.
    """
    definitions: list[tuple[str, str, dict[str, Any], Callable]] = [
        (
            "scratch_write",
            "Write or update an entry in the scratchpad (ephemeral working memory).",
            _WRITE_SCHEMA,
            _make_write(provider),
        ),
        (
            "scratch_read",
            "Read a scratchpad entry by key, or list all entries when key is omitted.",
            _READ_SCHEMA,
            _make_read(provider),
        ),
        (
            "scratch_search",
            "Search scratchpad entries by key/content/tags (case-insensitive substring match).",
            _SEARCH_SCHEMA,
            _make_search(provider),
        ),
        (
            "scratch_delete",
            "Delete a scratchpad entry by key.",
            _DELETE_SCHEMA,
            _make_delete(provider),
        ),
    ]

    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable] = {}
    for name, description, schema, executor in definitions:
        specs[name] = ToolSpec(
            name=name, description=description, parameters=schema, is_local=True
        )
        executors[name] = executor
    return specs, executors
