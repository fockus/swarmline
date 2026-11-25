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
from typing import TYPE_CHECKING, Any

import structlog

from swarmline.observability.redaction import redact_secrets
from swarmline.runtime.types import ToolSpec
from swarmline.tools.protocols import BinaryReadProvider, SandboxProvider

if TYPE_CHECKING:
    from swarmline.runtime.thin.coding_profile import CodingProfileConfig

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

_EDIT_ANCHOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Путь к файлу"},
        "old_string": {"type": "string", "description": "Строка для замены"},
        "new_string": {"type": "string", "description": "Строка-замена"},
        "anchor": {
            "type": "string",
            "description": (
                "REQUIRED in anchor mode: sha256 hexdigest (64 hex chars) of the "
                "exact matched slice as last read from the file.  The edit is rejected "
                "if omitted, empty, whitespace-only, or if the file content at the "
                "target changed since the anchor was computed."
            ),
        },
    },
    "required": ["path", "old_string", "new_string", "anchor"],
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

_MULTI_FILE_EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["path", "old_string", "new_string"],
            },
            "description": (
                "Массив правок [{path, old_string, new_string}] по нескольким файлам. "
                "Транзакционно: либо все применяются, либо ни одной (all-or-nothing)."
            ),
        },
    },
    "required": ["edits"],
}

_MULTI_FILE_EDIT_ANCHOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "anchor": {
                        "type": "string",
                        "description": (
                            "REQUIRED in anchor mode: sha256 hexdigest (64 hex chars) of the "
                            "exact matched slice as last read from the file.  The edit is "
                            "rejected (stale_anchor) if omitted, empty, or if the file content "
                            "at the target changed since the anchor was computed."
                        ),
                    },
                },
                "required": ["path", "old_string", "new_string", "anchor"],
            },
            "description": (
                "Массив правок [{path, old_string, new_string, anchor}] по нескольким файлам. "
                "anchor ОБЯЗАТЕЛЕН: sha256 целевого фрагмента — отклоняет правку при несовпадении. "
                "Транзакционно: либо все применяются, либо ни одной (all-or-nothing)."
            ),
        },
    },
    "required": ["edits"],
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

                if not isinstance(sandbox, BinaryReadProvider):
                    return _make_json_error(
                        "PDF extraction requires a sandbox with binary read support"
                    )
                raw = await sandbox.read_file_bytes(path)
                content = await extract_pdf(raw)
                return json.dumps({"status": "ok", "content": content})

            # Jupyter notebook extraction
            if ext == ".ipynb":
                from swarmline.tools.extractors import extract_jupyter

                notebook = await sandbox.read_file(path)
                content = await extract_jupyter(notebook)
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
                return json.dumps(
                    {
                        "status": "ok",
                        "type": "image",
                        "data": data,
                        "media_type": _IMAGE_EXTENSIONS[ext],
                    }
                )

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
            return json.dumps(
                {"status": "ok", "path": path, "edits_applied": len(edits)}
            )
        except Exception as e:
            return _make_json_error(str(e))

    return executor


def _create_tolerant_edit_executor(sandbox: SandboxProvider) -> Callable:
    """Tolerant single-file `edit`: fuzzy cascade + structured failure (REQ-SCA-001/002)."""

    async def executor(args: dict) -> str:
        from swarmline.tools.edit.strategy import Hunk, SearchReplaceStrategy

        path = args.get("path", "")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        if not path or not old_string:
            return _make_json_error("path и old_string обязательны")
        try:
            outcome = await SearchReplaceStrategy().apply(
                (Hunk(path=path, old=old_string, new=new_string),),
                sandbox,
                transactional=False,
            )
        except Exception as e:
            return _make_json_error(str(e))
        return _serialize_edit_outcome(outcome, path=path)

    return executor


def _create_multi_file_edit_executor(sandbox: SandboxProvider) -> Callable:
    """Transactional multi-file `multi_file_edit`: dry-run all → all-or-nothing (REQ-SCA-003/004).

    The V4APatchStrategy (with its single AsyncPathLock) is constructed ONCE here,
    outside the inner async executor, so all calls share the same lock registry
    (F3 fix: concurrent overlapping calls on the same paths serialize correctly).
    """
    from swarmline.tools.edit.strategy import Hunk, V4APatchStrategy

    # Single shared strategy instance — its AsyncPathLock is reused across calls.
    _strategy = V4APatchStrategy()

    async def executor(args: dict) -> str:
        raw_edits = args.get("edits", [])
        if not raw_edits:
            return _make_json_error("edits обязателен")
        try:
            hunks = tuple(
                Hunk(
                    path=e.get("path", ""),
                    old=e.get("old_string", ""),
                    new=e.get("new_string", ""),
                )
                for e in raw_edits
            )
            if any(not h.path or not h.old for h in hunks):
                return _make_json_error("каждый edit требует path и old_string")
            outcome = await _strategy.apply(hunks, sandbox, transactional=True)
        except Exception as e:
            return _make_json_error(str(e))
        return _serialize_edit_outcome(outcome)

    return executor


def _create_anchor_edit_executor(sandbox: SandboxProvider) -> Callable:
    """Single-file `edit` executor backed by AnchorEditStrategy (REQ-RCA-070).

    Fail-closed: ``anchor`` is REQUIRED and must be non-empty.  A missing or
    empty anchor is rejected before any file access — no unanchored write path
    exists in anchor mode.  AnchorEditStrategy is constructed once, shared.
    """
    from swarmline.tools.edit.anchor import AnchoredHunk, AnchorEditStrategy

    _strategy = AnchorEditStrategy()

    async def executor(args: dict) -> str:
        path = args.get("path", "")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        anchor = (args.get("anchor") or "").strip()
        if not path or not old_string:
            return _make_json_error("path и old_string обязательны")
        if not anchor:
            return _make_json_error(
                "anchor is required when edit_strategy='anchor'; "
                "provide sha256 hexdigest of the target slice as last read"
            )
        try:
            outcome = await _strategy.apply(
                (
                    AnchoredHunk(
                        path=path, old=old_string, new=new_string, anchor=anchor
                    ),
                ),
                sandbox,
                transactional=True,
            )
        except Exception as e:  # noqa: BLE001
            return _make_json_error(str(e))
        return _serialize_edit_outcome(outcome, path=path)

    return executor


def _create_anchor_multi_file_edit_executor(sandbox: SandboxProvider) -> Callable:
    """Multi-file `multi_file_edit` executor backed by AnchorEditStrategy (REQ-RCA-070).

    Fail-closed: every edit item MUST supply a non-empty ``anchor``.  If ANY
    item is missing or has an empty anchor the ENTIRE call is rejected before
    any file is touched — no unanchored write path exists in anchor mode.
    AnchorEditStrategy is constructed once so its AsyncPathLock is shared.
    """
    from swarmline.tools.edit.anchor import AnchoredHunk, AnchorEditStrategy

    _strategy = AnchorEditStrategy()

    async def executor(args: dict) -> str:
        raw_edits = args.get("edits", [])
        if not raw_edits:
            return _make_json_error("edits обязателен")
        try:
            hunks: list[AnchoredHunk] = []
            for idx, e in enumerate(raw_edits):
                path = e.get("path", "")
                old_string = e.get("old_string", "")
                new_string = e.get("new_string", "")
                anchor = (e.get("anchor") or "").strip()
                if not path or not old_string:
                    return _make_json_error("каждый edit требует path и old_string")
                if not anchor:
                    return _make_json_error(
                        f"anchor is required for every edit when edit_strategy='anchor'; "
                        f"edit[{idx}] (path={path!r}) is missing an anchor — "
                        f"provide sha256 hexdigest of the target slice as last read"
                    )
                hunks.append(
                    AnchoredHunk(
                        path=path, old=old_string, new=new_string, anchor=anchor
                    )
                )
            outcome = await _strategy.apply(tuple(hunks), sandbox, transactional=True)
        except Exception as e:  # noqa: BLE001
            return _make_json_error(str(e))
        return _serialize_edit_outcome(outcome)

    return executor


def _serialize_edit_outcome(outcome: Any, *, path: str | None = None) -> str:
    """Serialize an EditOutcome into a JSON tool result (REQ-SCA-002)."""
    first_failure = next((r for r in outcome.results if r.status == "failed"), None)
    payload: dict[str, Any] = {
        "status": "ok" if outcome.applied else "error",
        "applied": outcome.applied,
        "mode": outcome.mode,
        "message": outcome.message,
        "results": [
            {
                "path": r.path,
                "status": r.status,
                "failure": r.failure,
                "detail": r.detail,
                "match_strategy": r.match_strategy,
            }
            for r in outcome.results
        ],
    }
    if path is not None:
        payload["path"] = path
    if not outcome.applied and first_failure is not None:
        # Surface the leading failure at top level for easy model consumption.
        payload["failure"] = first_failure.failure
        payload["detail"] = first_failure.detail
    return json.dumps(payload)


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
            return json.dumps(
                {"status": "ok", "matches": [], "note": "path рекомендуется"}
            )
        except TimeoutError:
            return _make_json_error(
                "Regex timeout — возможно catastrophic backtracking"
            )
        except Exception as e:
            return _make_json_error(str(e))

    return executor


# ---------------------------------------------------------------------------
# Factory: sandbox tools
# ---------------------------------------------------------------------------


def create_sandbox_tools(
    sandbox: SandboxProvider,
    *,
    config: CodingProfileConfig | None = None,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Create sandbox tools.

    Args:
        sandbox: SandboxProvider for file/shell tools.
        config: Optional CodingProfileConfig. Reserved for flag-gated features
                introduced in Tasks 1-8 (B2 propagation seam). When None or all
                flags at defaults, output is byte-identical to the no-config call.

    Returns:
        Tuple: (specs dict, executors dict).
    """
    tools: list[tuple[str, str, dict, Callable]] = [
        (
            "bash",
            "Выполнить shell-команду в sandbox",
            _BASH_SCHEMA,
            _create_bash_executor(sandbox),
        ),
        (
            "read",
            "Прочитать файл из workspace",
            _READ_SCHEMA,
            _create_read_executor(sandbox),
        ),
        (
            "write",
            "Записать файл в workspace",
            _WRITE_SCHEMA,
            _create_write_executor(sandbox),
        ),
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
        (
            "ls",
            "Список файлов в директории workspace",
            _LS_SCHEMA,
            _create_ls_executor(sandbox),
        ),
        (
            "glob",
            "Поиск файлов по glob-паттерну",
            _GLOB_SCHEMA,
            _create_glob_executor(sandbox),
        ),
        (
            "grep",
            "Поиск текста по regex в файлах",
            _GREP_SCHEMA,
            _create_grep_executor(sandbox),
        ),
    ]

    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable] = {}

    for name, desc, schema, executor in tools:
        specs[name] = ToolSpec(name=name, description=desc, parameters=schema)
        executors[name] = executor

    # B2 seam: legacy path (config is None or edit_strategy == "legacy") is
    # byte-identical to the original — no tolerant routing, no extra tools.
    if config is not None and config.edit_strategy != "legacy":
        if config.edit_strategy == "anchor":
            # REQ-RCA-070: hash-anchored transactional strategy.  Both single-file
            # and multi-file tools are backed by AnchorEditStrategy.  The spec AND
            # executor for 'edit' are both replaced so the model surface (schema)
            # matches the executor contract: anchor REQUIRED, fail-closed on missing.
            # Default ("legacy") path is untouched.
            specs["edit"] = ToolSpec(
                name="edit",
                description="Заменить подстроку в файле (str_replace, hash-якорь обязателен)",
                parameters=_EDIT_ANCHOR_SCHEMA,
            )
            executors["edit"] = _create_anchor_edit_executor(sandbox)
            specs["multi_file_edit"] = ToolSpec(
                name="multi_file_edit",
                description=(
                    "Транзакционная правка нескольких файлов с hash-якорями (all-or-nothing)"
                ),
                parameters=_MULTI_FILE_EDIT_ANCHOR_SCHEMA,
            )
            executors["multi_file_edit"] = _create_anchor_multi_file_edit_executor(
                sandbox
            )
        else:
            # Tolerant single-file `edit` replaces the legacy first-occurrence one.
            # The visible ToolSpec is unchanged (same name/description/schema) so the
            # model surface is stable; only the executor becomes tolerant.
            executors["edit"] = _create_tolerant_edit_executor(sandbox)
            # New opt-in transactional multi-file edit tool.
            specs["multi_file_edit"] = ToolSpec(
                name="multi_file_edit",
                description="Транзакционная правка нескольких файлов (all-or-nothing)",
                parameters=_MULTI_FILE_EDIT_SCHEMA,
            )
            executors["multi_file_edit"] = _create_multi_file_edit_executor(sandbox)

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
            _log.warning(
                "web_fetch_failed",
                url=redact_secrets(url.strip())[:200],
                error=redact_secrets(str(e)),
                exc_type=type(e).__name__,
            )
            return _make_json_error("web_fetch failed")

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
                        {"title": r.title, "url": r.url, "snippet": r.snippet}
                        for r in results
                    ],
                }
            )
        except Exception as e:
            _log.warning(
                "web_search_failed",
                query=query[:100],
                error=redact_secrets(str(e)),
                exc_type=type(e).__name__,
            )
            return json.dumps({"status": "error", "message": redact_secrets(str(e))})

    specs["web_fetch"] = ToolSpec(
        name="web_fetch",
        description="Получить содержимое URL",
        parameters=_WEB_FETCH_SCHEMA,
    )
    specs["web_search"] = ToolSpec(
        name="web_search",
        description="Поиск в интернете",
        parameters=_WEB_SEARCH_SCHEMA,
    )
    executors["web_fetch"] = fetch_executor
    executors["web_search"] = search_executor

    return specs, executors
