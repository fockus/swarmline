"""Agent-facing ``workspace.*`` tools (read/write/update_todo/update_plan/search/list_files).

Ported (as a ``(specs, executors)`` factory) from Aura's
``infrastructure/tools_impl/workspace_tools.py``, minus the RAG retriever
(deferred) -- search uses ``FileRegistry.search()`` (lexical) only. Split out
of ``tools.py`` to respect the file-size ceiling; see also ``tools_artifact.py``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from swarmline.artifacts.file_registry import FileRegistry
from swarmline.artifacts.live_files import LiveFilesManager
from swarmline.artifacts.run_root import ArtifactRoot
from swarmline.path_safety import build_isolated_path
from swarmline.runtime.types import ToolSpec

_WRITABLE_TOP_DIRS = {"notes", "data", "drafts", "code", "charts"}
_PROTECTED_TOP_DIRS = {"tool_outputs", "snapshots", ".versions"}
_LIVE_FILENAMES = {
    "goal.md",
    "plan.md",
    "todo.md",
    "status.md",
    "sources.md",
    "constraints.md",
}


def create_workspace_tools(
    root: ArtifactRoot,
    file_registry: FileRegistry,
    live_files: LiveFilesManager,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Create ``workspace.read/write/update_todo/update_plan/search/list_files`` tools."""

    async def workspace_read_executor(args: dict[str, Any]) -> str:
        filename = args.get("filename", "")
        if not filename:
            return json.dumps({"status": "error", "message": "filename is required"})
        try:
            file_path = build_isolated_path(root.path, filename)
        except ValueError:
            return json.dumps(
                {"status": "error", "message": "access denied: path traversal"}
            )
        if not file_path.is_file():
            return json.dumps(
                {"status": "error", "message": f"file not found: {filename}"}
            )
        content = file_path.read_text(encoding="utf-8")
        return json.dumps({"status": "ok", "content": content, "size": len(content)})

    async def workspace_write_executor(args: dict[str, Any]) -> str:
        filename = args.get("filename", "")
        content = args.get("content", "")
        if not filename or not content:
            return json.dumps(
                {"status": "error", "message": "filename and content are required"}
            )
        try:
            file_path = build_isolated_path(root.path, filename)
        except ValueError:
            return json.dumps(
                {"status": "error", "message": "access denied: path traversal"}
            )

        # MAJOR 1 fix: run every check against the CANONICAL (post-resolve)
        # path, not the raw `filename` -- `notes/../tool_outputs/x` passes
        # build_isolated_path (it stays under root) but must still be treated
        # as `tool_outputs/x` for the protected/live-file/category checks.
        canonical = str(file_path.relative_to(root.path))
        canonical_parts = Path(canonical).parts
        top_dir = canonical_parts[0] if canonical_parts else ""
        if top_dir in _PROTECTED_TOP_DIRS:
            return json.dumps(
                {"status": "error", "message": f"{top_dir}/ is immutable"}
            )

        # MAJOR 1(b) fix: root-level dotfiles (`.artifacts.json`,
        # `.registry.md`/`.registry.json`, `.journal.jsonl`, ...) are internal
        # index/state files, not user content -- letting an agent overwrite
        # them would poison artifact.load's id -> path lookups.
        if len(canonical_parts) == 1 and canonical_parts[0].startswith("."):
            return json.dumps(
                {
                    "status": "error",
                    "message": f"{canonical} is an internal index file and is protected",
                }
            )

        if canonical in _LIVE_FILENAMES:
            version = live_files.update_file(canonical, content)
            return json.dumps({"status": "ok", "version": version})

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        category = top_dir if top_dir in _WRITABLE_TOP_DIRS else "other"
        file_registry.add(
            path=canonical,
            description=content[:80].replace("\n", " "),
            category=category,
            size_bytes=len(content.encode("utf-8")),
        )
        return json.dumps({"status": "ok", "size": len(content)})

    async def workspace_update_todo_executor(args: dict[str, Any]) -> str:
        content = args.get("content", "")
        if not content:
            return json.dumps({"status": "error", "message": "content is required"})
        version = live_files.update_todo(content)
        return json.dumps({"status": "ok", "version": version})

    async def workspace_update_plan_executor(args: dict[str, Any]) -> str:
        content = args.get("content", "")
        if not content:
            return json.dumps({"status": "error", "message": "content is required"})
        version = live_files.update_plan(content)
        return json.dumps({"status": "ok", "version": version})

    async def workspace_search_executor(args: dict[str, Any]) -> str:
        query = args.get("query", "")
        max_results = args.get("max_results", 10)
        if not query:
            return json.dumps({"status": "error", "message": "query is required"})
        results = file_registry.search(query, max_results=max_results)
        return json.dumps(
            {
                "status": "ok",
                "results": [
                    {
                        "path": e.path,
                        "description": e.description,
                        "category": e.category,
                    }
                    for e in results
                ],
            }
        )

    async def workspace_list_files_executor(args: dict[str, Any]) -> str:
        directory = args.get("directory") or ""
        try:
            search_path = (
                build_isolated_path(root.path, directory) if directory else root.path
            )
        except ValueError:
            return json.dumps(
                {"status": "error", "message": "access denied: path traversal"}
            )
        if not search_path.exists():
            return json.dumps(
                {"status": "error", "message": f"directory not found: {directory}"}
            )
        files = [
            str(p.relative_to(root.path)) for p in search_path.rglob("*") if p.is_file()
        ]
        return json.dumps({"status": "ok", "files": sorted(files)})

    specs = {
        "workspace.read": ToolSpec(
            name="workspace.read",
            description="Read a workspace file (e.g. todo.md, notes/step_001.md).",
            parameters={
                "type": "object",
                "properties": {"filename": {"type": "string"}},
                "required": ["filename"],
            },
        ),
        "workspace.write": ToolSpec(
            name="workspace.write",
            description=(
                "Write a workspace file (notes/, data/, drafts/, code/, charts/, "
                "or a live file)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["filename", "content"],
            },
        ),
        "workspace.update_todo": ToolSpec(
            name="workspace.update_todo",
            description="Overwrite todo.md (versioned).",
            parameters={
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
            },
        ),
        "workspace.update_plan": ToolSpec(
            name="workspace.update_plan",
            description="Overwrite plan.md (versioned).",
            parameters={
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
            },
        ),
        "workspace.search": ToolSpec(
            name="workspace.search",
            description="Lexical search over the File Registry (path/description/category).",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        ),
        "workspace.list_files": ToolSpec(
            name="workspace.list_files",
            description="List files in the workspace (optionally under a subdirectory).",
            parameters={
                "type": "object",
                "properties": {"directory": {"type": "string"}},
            },
        ),
    }
    executors: dict[str, Callable] = {
        "workspace.read": workspace_read_executor,
        "workspace.write": workspace_write_executor,
        "workspace.update_todo": workspace_update_todo_executor,
        "workspace.update_plan": workspace_update_plan_executor,
        "workspace.search": workspace_search_executor,
        "workspace.list_files": workspace_list_files_executor,
    }
    return specs, executors
