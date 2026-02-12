"""Memory Bank tools — 5 инструментов для работы с банком памяти.

Прокидываются во ВСЕ runtime одинаково (claude_sdk, deepagents, thin).
KISS: каждый executor ≤25 строк.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from cognitia.memory_bank.protocols import MemoryBankProvider
from cognitia.runtime.types import ToolSpec

_READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"path": {"type": "string", "description": "Путь к файлу в банке памяти (e.g. 'MEMORY.md', 'plans/feature.md')"}},
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
    "properties": {"prefix": {"type": "string", "description": "Фильтр по prefix/подпапке (опционально)", "default": ""}},
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
        "memory_read": ToolSpec(name="memory_read", description="Прочитать файл из банка памяти", parameters=_READ_SCHEMA),
        "memory_write": ToolSpec(name="memory_write", description="Записать файл в банк памяти", parameters=_WRITE_SCHEMA),
        "memory_append": ToolSpec(name="memory_append", description="Дописать в конец файла в банке памяти", parameters=_APPEND_SCHEMA),
        "memory_list": ToolSpec(name="memory_list", description="Список файлов в банке памяти", parameters=_LIST_SCHEMA),
        "memory_delete": ToolSpec(name="memory_delete", description="Удалить файл из банка памяти", parameters=_DELETE_SCHEMA),
    }

    executors: dict[str, Callable] = {
        "memory_read": memory_read,
        "memory_write": memory_write,
        "memory_append": memory_append,
        "memory_list": memory_list,
        "memory_delete": memory_delete,
    }

    return specs, executors
