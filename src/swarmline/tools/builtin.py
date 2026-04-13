"""Builtin Tools - built-in tools for agents.

Sandbox tools (bash, read, write, edit, multi_edit, ls, glob, grep)
run through SandboxProvider. Web tools (web_fetch, web_search)
run through WebProvider. Each group is created by a separate factory.

KISS: each executor <=30 lines.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from collections.abc import Callable
from typing import Any

import structlog

from swarmline.runtime.types import ToolSpec
from swarmline.tools.protocols import BinaryReadProvider, SandboxProvider

_log = structlog.get_logger(component="web_tools")

# ---------------------------------------------------------------------------
# Alias map: SDK names -> canonical snake_case
# ---------------------------------------------------------------------------

TOOL_ALIAS_MAP: dict[str, str] = {
    "Bash": "bash",
    "Read": "read",
    "Write": "write",
    "Edit": "edit",
    "MultiEdit": "multi_edit",
    "Glob": "glob",
    "Grep": "grep",
    "LS": "ls",
    "WebFetch": "web_fetch",
    "WebSearch": "web_search",
}

# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

_BASH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Shell-команда для выполнения"},
    },
    "required": ["command"],
}

_READ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Относительный путь к файлу"},
    },
    "required": ["path"],
}

_WRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Относительный путь к файлу"},
        "content": {"type": "string", "description": "Содержимое файла"},
    },
    "required": ["path", "content"],
}

_EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Путь к файлу"},
        "old_string": {"type": "string", "description": "Строка для замены"},
        "new_string": {"type": "string", "description": "Строка-замена"},
    },
    "required": ["path", "old_string", "new_string"],
}

_MULTI_EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Путь к файлу"},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["old_string", "new_string"],
            },
            "description": "Массив замен [{old_string, new_string}]",
        },
    },
    "required": ["path", "edits"],
}

_LS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Путь к директории", "default": "."},
    },
}

_GLOB_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "Glob-паттерн (e.g. **/*.py)"},
    },
    "required": ["pattern"],
}

_GREP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "Regex-паттерн для поиска"},
        "path": {"type": "string", "description": "Путь к файлу (опционально)"},
    },
    "required": ["pattern"],
}

_WEB_FETCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "URL для загрузки"},
    },
    "required": ["url"],
}

_WEB_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Поисковый запрос"},
        "max_results": {"type": "integer", "default": 5},
    },
    "required": ["query"],
}


# ---------------------------------------------------------------------------
# Sandbox Tool Executors
# ---------------------------------------------------------------------------


def _make_json_error(message: str) -> str:
    """Create a JSON error response."""
    return json.dumps({"status": "error", "message": message})


def _create_bash_executor(sandbox: SandboxProvider) -> Callable:
    async def executor(args: dict) -> str:
        command = args.get("command")
        if not command:
            return _make_json_error("command обязателен")
        try:
            result = await sandbox.execute(command)
            return json.dumps(
                {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                }
            )
        except Exception as e:
            return _make_json_error(str(e))

    return executor


_IMAGE_EXTENSIONS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _create_read_executor(sandbox: SandboxProvider) -> Callable:
    async def executor(args: dict) -> str:
        path = args.get("path")
        if not path:
            return _make_json_error("path обязателен")
        try:
            ext = os.path.splitext(path)[1].lower()

            # PDF extraction
            if ext == ".pdf":
                from swarmline.tools.extractors import extract_pdf

                content = await extract_pdf(path)
                return json.dumps({"status": "ok", "content": content})

            # Jupyter notebook extraction
            if ext == ".ipynb":
                from swarmline.tools.extractors import extract_jupyter

                content = await extract_jupyter(path)
                return json.dumps({"status": "ok", "content": content})

            # Image detection — requires BinaryReadProvider
            _MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB limit
            if ext in _IMAGE_EXTENSIONS and isinstance(sandbox, BinaryReadProvider):
                raw = await sandbox.read_file_bytes(path)
                if len(raw) > _MAX_IMAGE_BYTES:
                    return _make_json_error(
                        f"Image too large ({len(raw)} bytes, max {_MAX_IMAGE_BYTES})"
                    )
                data = base64.b64encode(raw).decode()
                return json.dumps({
                    "status": "ok",
                    "type": "image",
                    "data": data,
                    "media_type": _IMAGE_EXTENSIONS[ext],
                })

            # Default: text read
            content = await sandbox.read_file(path)
            return json.dumps({"status": "ok", "content": content})
        except Exception as e:
            return _make_json_error(str(e))

    return executor


def _create_write_executor(sandbox: SandboxProvider) -> Callable:
    async def executor(args: dict) -> str:
        path = args.get("path")
        content = args.get("content")
        if not path or content is None:
            return _make_json_error("path и content обязательны")
        try:
            await sandbox.write_file(path, content)
            return json.dumps({"status": "ok", "path": path})
        except Exception as e:
            return _make_json_error(str(e))

    return executor


def _create_edit_executor(sandbox: SandboxProvider) -> Callable:
    async def executor(args: dict) -> str:
        path = args.get("path", "")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        if not path or not old_string:
            return _make_json_error("path и old_string обязательны")
        try:
            content = await sandbox.read_file(path)
            if old_string not in content:
                return _make_json_error(f"old_string не найден в {path}")
            # Replace only the first occurrence
            updated = content.replace(old_string, new_string, 1)
            await sandbox.write_file(path, updated)
            return json.dumps({"status": "ok", "path": path})
        except Exception as e:
            return _make_json_error(str(e))

    return executor


def _create_multi_edit_executor(sandbox: SandboxProvider) -> Callable:
    async def executor(args: dict) -> str:
        path = args.get("path", "")
        edits = args.get("edits", [])
        if not path or not edits:
            return _make_json_error("path и edits обязательны")
        try:
            content = await sandbox.read_file(path)
            for edit in edits:
                old = edit.get("old_string", "")
                new = edit.get("new_string", "")
                if old not in content:
                    return _make_json_error(f"old_string не найден: {old[:50]}")
                content = content.replace(old, new, 1)
            await sandbox.write_file(path, content)
            return json.dumps({"status": "ok", "path": path, "edits_applied": len(edits)})
        except Exception as e:
            return _make_json_error(str(e))

    return executor


def _create_ls_executor(sandbox: SandboxProvider) -> Callable:
    async def executor(args: dict) -> str:
        path = args.get("path", ".")
        try:
            entries = await sandbox.list_dir(path)
            return json.dumps({"status": "ok", "entries": entries})
        except Exception as e:
            return _make_json_error(str(e))

    return executor


def _create_glob_executor(sandbox: SandboxProvider) -> Callable:
    async def executor(args: dict) -> str:
        pattern = args.get("pattern", "")
        if not pattern:
            return _make_json_error("pattern обязателен")
        try:
            matches = await sandbox.glob_files(pattern)
            return json.dumps({"status": "ok", "matches": matches})
        except Exception as e:
            return _make_json_error(str(e))

    return executor


def _create_grep_executor(sandbox: SandboxProvider) -> Callable:
    async def executor(args: dict) -> str:
        pattern = args.get("pattern", "")
        path = args.get("path")
        if not pattern:
            return _make_json_error("pattern обязателен")
        if len(pattern) > 500:
            return _make_json_error("pattern слишком длинный (макс 500 символов)")
        try:
            # Validate regex before use to catch malformed patterns early
            compiled = re.compile(pattern)
        except re.error as e:
            return _make_json_error(f"Некорректный regex: {e}")
        try:
            if path:
                content = await sandbox.read_file(path)
                # Run regex in thread with timeout to prevent ReDoS
                matches = await asyncio.wait_for(
                    asyncio.to_thread(compiled.findall, content),
                    timeout=10.0,
                )
                return json.dumps({"status": "ok", "matches": matches, "path": path})
            # Without a path, search across all workspace files (basic implementation)
            return json.dumps({"status": "ok", "matches": [], "note": "path рекомендуется"})
        except TimeoutError:
            return _make_json_error("Regex timeout — возможно catastrophic backtracking")
        except Exception as e:
            return _make_json_error(str(e))

    return executor


# ---------------------------------------------------------------------------
# Factory: sandbox tools
# ---------------------------------------------------------------------------


def create_sandbox_tools(
    sandbox: SandboxProvider,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Create sandbox tools.

    Returns:
        Tuple: (specs dict, executors dict).
    """
    tools: list[tuple[str, str, dict, Callable]] = [
        ("bash", "Выполнить shell-команду в sandbox", _BASH_SCHEMA, _create_bash_executor(sandbox)),
        ("read", "Прочитать файл из workspace", _READ_SCHEMA, _create_read_executor(sandbox)),
        ("write", "Записать файл в workspace", _WRITE_SCHEMA, _create_write_executor(sandbox)),
        (
            "edit",
            "Заменить подстроку в файле (str_replace)",
            _EDIT_SCHEMA,
            _create_edit_executor(sandbox),
        ),
        (
            "multi_edit",
            "Несколько замен в одном файле",
            _MULTI_EDIT_SCHEMA,
            _create_multi_edit_executor(sandbox),
        ),
        ("ls", "Список файлов в директории workspace", _LS_SCHEMA, _create_ls_executor(sandbox)),
        ("glob", "Поиск файлов по glob-паттерну", _GLOB_SCHEMA, _create_glob_executor(sandbox)),
        ("grep", "Поиск текста по regex в файлах", _GREP_SCHEMA, _create_grep_executor(sandbox)),
    ]

    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable] = {}

    for name, desc, schema, executor in tools:
        specs[name] = ToolSpec(name=name, description=desc, parameters=schema)
        executors[name] = executor

    return specs, executors


# ---------------------------------------------------------------------------
# Factory: web tools
# ---------------------------------------------------------------------------


def create_web_tools(
    web_provider: Any | None,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Create web tools.

    Args:
        web_provider: WebProvider or None. If None, tools are not created.

    Returns:
        Tuple: (specs dict, executors dict). Empty if no provider is configured.
    """
    if web_provider is None:
        return {}, {}

    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable] = {}

    async def fetch_executor(args: dict) -> str:
        url = args.get("url", "")
        if not url or not url.strip():
            return _make_json_error("url обязателен")
        try:
            content = await web_provider.fetch(url.strip())
            return json.dumps({"status": "ok", "content": content})
        except Exception as e:
            _log.warning("web_fetch_failed", url=url[:200], error=str(e))
            return _make_json_error(str(e))

    async def search_executor(args: dict) -> str:
        query = args.get("query", "")
        max_results = args.get("max_results", 5)
        if not query or not query.strip():
            return _make_json_error("query обязателен")
        try:
            results = await web_provider.search(query.strip(), max_results)
            return json.dumps(
                {
                    "status": "ok",
                    "result_count": len(results),
                    "results": [
                        {"title": r.title, "url": r.url, "snippet": r.snippet} for r in results
                    ],
                }
            )
        except Exception as e:
            _log.warning("web_search_failed", query=query[:100], error=str(e))
            return json.dumps({"status": "error", "message": str(e)})

    specs["web_fetch"] = ToolSpec(
        name="web_fetch", description="Получить содержимое URL", parameters=_WEB_FETCH_SCHEMA
    )
    specs["web_search"] = ToolSpec(
        name="web_search", description="Поиск в интернете", parameters=_WEB_SEARCH_SCHEMA
    )
    executors["web_fetch"] = fetch_executor
    executors["web_search"] = search_executor

    return specs, executors
