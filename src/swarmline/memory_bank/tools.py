"""Memory Bank tools — 5 инструментов для работы с банком памяти.

Прокидываются во ВСЕ runtime одинаково (claude_sdk, deepagents, thin).
KISS: каждый executor ≤25 строк.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from swarmline.memory_bank.protocols import MemoryBankProvider
from swarmline.runtime.types import ToolSpec

_READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Путь к файлу в банке памяти (e.g. 'MEMORY.md', 'plans/feature.md')",
        }
    },
    "required": ["path"],
}

_WRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Путь к файлу"},
        "content": {"type": "string", "description": "Содержимое файла"},
    },
    "required": ["path", "content"],
}

_APPEND_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Путь к файлу"},
        "content": {"type": "string", "description": "Содержимое для добавления в конец"},
    },
    "required": ["path", "content"],
}

_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "prefix": {
            "type": "string",
            "description": "Фильтр по prefix/подпапке (опционально)",
            "default": "",
        }
    },
}

_DELETE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"path": {"type": "string", "description": "Путь к файлу для удаления"}},
    "required": ["path"],
}


def create_memory_bank_tools(
    provider: MemoryBankProvider,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Создать 5 memory_* tools.

    Returns:
        Tuple: (specs dict, executors dict).
    """

    async def memory_read(args: dict) -> str:
        path = args.get("path", "")
        if not path:
            return json.dumps({"status": "error", "message": "path обязателен"})
        try:
            content = await provider.read_file(path)
            if content is None:
                return json.dumps({"status": "not_found", "path": path})
            return json.dumps({"status": "ok", "content": content, "path": path})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def memory_write(args: dict) -> str:
        path = args.get("path", "")
        content = args.get("content", "")
        if not path:
            return json.dumps({"status": "error", "message": "path обязателен"})
        try:
            await provider.write_file(path, content)
            return json.dumps({"status": "ok", "path": path})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def memory_append(args: dict) -> str:
        path = args.get("path", "")
        content = args.get("content", "")
        if not path:
            return json.dumps({"status": "error", "message": "path обязателен"})
        try:
            await provider.append_to_file(path, content)
            return json.dumps({"status": "ok", "path": path})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def memory_list(args: dict) -> str:
        prefix = args.get("prefix", "")
        try:
            files = await provider.list_files(prefix)
            return json.dumps({"status": "ok", "files": files})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    async def memory_delete(args: dict) -> str:
        path = args.get("path", "")
        if not path:
            return json.dumps({"status": "error", "message": "path обязателен"})
        try:
            await provider.delete_file(path)
            return json.dumps({"status": "ok", "path": path})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    specs = {
        "memory_read": ToolSpec(
            name="memory_read",
            description="Прочитать файл из банка памяти",
            parameters=_READ_SCHEMA,
        ),
        "memory_write": ToolSpec(
            name="memory_write", description="Записать файл в банк памяти", parameters=_WRITE_SCHEMA
        ),
        "memory_append": ToolSpec(
            name="memory_append",
            description="Дописать в конец файла в банке памяти",
            parameters=_APPEND_SCHEMA,
        ),
        "memory_list": ToolSpec(
            name="memory_list", description="Список файлов в банке памяти", parameters=_LIST_SCHEMA
        ),
        "memory_delete": ToolSpec(
            name="memory_delete",
            description="Удалить файл из банка памяти",
            parameters=_DELETE_SCHEMA,
        ),
    }

    executors: dict[str, Callable] = {
        "memory_read": memory_read,
        "memory_write": memory_write,
        "memory_append": memory_append,
        "memory_list": memory_list,
        "memory_delete": memory_delete,
    }

    return specs, executors


def create_knowledge_tools(
    store: Any,  # KnowledgeStore (InMemory or Default)
    searcher: Any,  # KnowledgeSearcher (InMemory or Default)
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Create knowledge bank tools for agent use.

    Returns:
        Tuple: (specs dict, executors dict) with 3 tools:
        knowledge_search, knowledge_save_note, knowledge_get_context.
    """

    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable] = {}

    # --- knowledge_search ---

    specs["knowledge_search"] = ToolSpec(
        name="knowledge_search",
        description="Search the knowledge bank for relevant entries by text query.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text"},
                "top_k": {"type": "integer", "description": "Max results", "default": 5},
            },
            "required": ["query"],
        },
        is_local=True,
    )

    async def _search(args: dict) -> str:
        query = args.get("query", "")
        top_k = int(args.get("top_k", 5))
        results = await searcher.search(query, top_k=top_k)
        return json.dumps(
            [
                {"path": r.path, "kind": r.kind, "tags": list(r.tags), "summary": r.summary}
                for r in results
            ],
            ensure_ascii=False,
        )

    executors["knowledge_search"] = _search

    # --- knowledge_save_note ---

    specs["knowledge_save_note"] = ToolSpec(
        name="knowledge_save_note",
        description="Save a knowledge note with tags and metadata.",
        parameters={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Note topic (used in filename)"},
                "content": {"type": "string", "description": "Note content (markdown)"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "importance": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "default": "medium",
                },
            },
            "required": ["topic", "content"],
        },
        is_local=True,
    )

    async def _save_note(args: dict) -> str:
        import time

        from swarmline.memory_bank.knowledge_types import DocumentMeta, KnowledgeEntry

        topic = args.get("topic", "untitled")
        content = args.get("content", "")
        tags_str = args.get("tags", "")
        importance = args.get("importance", "medium")

        tags = tuple(t.strip() for t in tags_str.split(",") if t.strip()) if tags_str else ()
        now = time.strftime("%Y-%m-%d")
        safe_topic = topic.lower().replace(" ", "-")
        safe_topic = "".join(c for c in safe_topic if c.isalnum() or c == "-")
        path = f"notes/{now}_{safe_topic}.md"

        entry = KnowledgeEntry(
            path=path,
            meta=DocumentMeta(kind="note", tags=tags, importance=importance, created=now, updated=now),
            content=content,
            size_bytes=len(content.encode("utf-8")),
        )
        await store.save(entry)
        return f"Saved note: {path}"

    executors["knowledge_save_note"] = _save_note

    # --- knowledge_get_context ---

    specs["knowledge_get_context"] = ToolSpec(
        name="knowledge_get_context",
        description="Get a summary of the knowledge bank state (recent entries, stats).",
        parameters={
            "type": "object",
            "properties": {},
        },
        is_local=True,
    )

    async def _get_context(args: dict) -> str:
        entries = await store.list_entries()
        by_kind: dict[str, int] = {}
        for e in entries:
            by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
        recent = sorted(entries, key=lambda e: e.updated, reverse=True)[:5]
        return json.dumps(
            {
                "total_entries": len(entries),
                "by_kind": by_kind,
                "recent": [{"path": e.path, "kind": e.kind, "summary": e.summary} for e in recent],
            },
            ensure_ascii=False,
        )

    executors["knowledge_get_context"] = _get_context

    return specs, executors
