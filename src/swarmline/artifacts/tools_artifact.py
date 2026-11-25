"""Agent-facing ``artifact.create``/``artifact.load`` tools.

Ported (as a ``(specs, executors)`` factory, matching ``todo/tools.py`` and
``scratchpad/tools.py``) from Aura's ``infrastructure/tools_impl/artifact_tools.py``.
Split out of ``tools.py`` to respect the file-size ceiling; see also
``tools_workspace.py`` for the ``workspace.*`` tools.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from swarmline.artifacts.file_registry import FileRegistry
from swarmline.artifacts.protocols import ArtifactStorePort
from swarmline.artifacts.registry import ArtifactRegistry
from swarmline.artifacts.run_root import ArtifactRoot
from swarmline.artifacts.types import Artifact, ArtifactType
from swarmline.path_safety import build_isolated_path
from swarmline.runtime.types import ToolSpec

_MIME_BY_EXT: dict[str, str] = {
    ".txt": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
    ".html": "text/html",
    ".xml": "application/xml",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".py": "text/x-python",
    ".md": "text/markdown",
}


def _guess_mime_type(filename: str) -> str:
    return _MIME_BY_EXT.get(
        os.path.splitext(filename)[1].lower(), "application/octet-stream"
    )


def _display_path(path: Path, root: ArtifactRoot) -> str:
    try:
        return str(path.relative_to(root.path))
    except ValueError:
        return str(path)


def _category_for(artifact_type: ArtifactType) -> str:
    directory = artifact_type.get_directory()
    return directory.split("/")[0] if directory else "live"


def _decode_preview(content: bytes, mime_type: str) -> str:
    """Best-effort text preview (first 500 chars) for text-ish MIME types."""
    if mime_type.startswith("text/") or mime_type in (
        "application/json",
        "application/xml",
    ):
        try:
            return content.decode("utf-8")[:500]
        except UnicodeDecodeError:
            return "(binary content)"
    return ""


def create_artifact_tools(
    store: ArtifactStorePort,
    *,
    registry: ArtifactRegistry | None = None,
    file_registry: FileRegistry | None = None,
) -> tuple[dict[str, ToolSpec], dict[str, Callable]]:
    """Create ``artifact.create``/``artifact.load`` tools.

    Args:
        store: ArtifactStorePort backend for single-file artifacts.
        registry: ArtifactRegistry (typed, directory-routed) -- required for
            multi-file-folder artifacts (``files=``).
        file_registry: FileRegistry -- when given, created artifacts are
            registered so they show up in ``.registry.md`` / context.
    """

    def _allowed_load_roots() -> list[Path]:
        """Roots a caller-supplied ``path`` may resolve under (path-traversal guard)."""
        roots: list[Path] = []
        base_path = getattr(store, "base_path", None)
        if base_path is not None:
            roots.append(Path(base_path))
        if registry is not None:
            roots.append(registry.root.path)
        if file_registry is not None:
            roots.append(file_registry.root.path)
        return roots

    def _validate_load_path(path: str) -> Path:
        """Resolve ``path`` under one of the allowed roots, or raise ValueError.

        Absolute paths and ``../`` traversal outside ALL configured roots are
        rejected -- ``build_isolated_path`` treats an absolute ``path`` as
        overriding the join, so the ``is_relative_to`` check still catches it.
        """
        for candidate_root in _allowed_load_roots():
            try:
                return build_isolated_path(candidate_root, path)
            except ValueError:
                continue
        raise ValueError(f"access denied: {path!r} is outside all configured roots")

    def _is_within_allowed_roots(candidate: Path) -> bool:
        """MAJOR 1(a) guard: a registry-resolved Artifact.path is NOT trusted
        by default -- a poisoned `.artifacts.json` entry (e.g. written before
        workspace.write started protecting internal index files) must still
        be rejected before ``is_dir()``/``store.load()`` ever touch it."""
        try:
            resolved = candidate.resolve()
        except OSError:
            return False
        for candidate_root in _allowed_load_roots():
            try:
                if resolved.is_relative_to(Path(candidate_root).resolve()):
                    return True
            except OSError:
                continue
        return False

    async def artifact_create_executor(args: dict[str, Any]) -> str:
        filename = args.get("filename", "")
        content = args.get("content")
        files = args.get("files")
        title = args.get("title") or filename or "artifact"
        mime_type = args.get("mime_type") or ""
        task_id = args.get("task_id") or "default"
        artifact_type = ArtifactType(args.get("type", "final"))

        try:
            if files:
                if registry is None:
                    return json.dumps(
                        {
                            "status": "error",
                            "message": "multi-file artifacts require a registry",
                        }
                    )
                artifact = registry.create(
                    type=artifact_type,
                    title=title,
                    files=files,
                    mime_type=mime_type or None,
                )
            elif registry is not None:
                # Route single-file creation through the registry too (when
                # given) so `.artifacts.json` indexes it and artifact.load can
                # find it by artifact_id (not just by the raw store path).
                if not filename or content is None:
                    return json.dumps(
                        {
                            "status": "error",
                            "message": "filename and content are required",
                        }
                    )
                artifact = registry.create(
                    type=artifact_type,
                    title=title,
                    content=content,
                    filename=filename,
                    mime_type=mime_type or _guess_mime_type(filename),
                )
            else:
                if not filename or content is None:
                    return json.dumps(
                        {
                            "status": "error",
                            "message": "filename and content are required",
                        }
                    )
                content_bytes = (
                    content.encode("utf-8") if isinstance(content, str) else content
                )
                artifact = await store.save(
                    task_id,
                    content_bytes,
                    filename,
                    mime_type or _guess_mime_type(filename),
                )
        except (OSError, ValueError) as e:
            return json.dumps({"status": "error", "message": str(e)})

        if file_registry is not None:
            file_registry.add(
                path=_display_path(Path(artifact.path), file_registry.root),
                description=title[:80],
                category=_category_for(artifact.type),
                size_bytes=artifact.size_bytes,
            )

        return json.dumps(
            {
                "status": "ok",
                "artifact_id": artifact.id,
                "path": str(artifact.path),
                "mime_type": artifact.mime_type,
                "size_bytes": artifact.size_bytes,
            }
        )

    async def artifact_load_executor(args: dict[str, Any]) -> str:
        artifact_id = args.get("artifact_id", "")
        path = args.get("path", "")
        file_within = args.get("file", "")
        mime_type = args.get("mime_type") or "application/octet-stream"

        if not artifact_id and not path:
            return json.dumps(
                {"status": "error", "message": "artifact_id or path is required"}
            )

        artifact = None
        if registry is not None and artifact_id:
            resolved = registry.get(artifact_id)
            if resolved is not None:
                if not _is_within_allowed_roots(Path(resolved.path)):
                    return json.dumps(
                        {
                            "status": "error",
                            "message": "access denied: artifact path outside allowed roots",
                        }
                    )
                artifact = resolved

        if artifact is None:
            if not path:
                return json.dumps(
                    {"status": "error", "message": f"artifact not found: {artifact_id}"}
                )
            try:
                validated_path = _validate_load_path(path)
            except ValueError:
                return json.dumps(
                    {"status": "error", "message": "access denied: path traversal"}
                )
            artifact = Artifact(
                id=artifact_id or "unknown",
                type=ArtifactType.TOOL_OUTPUT,
                title=args.get("title") or artifact_id or path,
                path=validated_path,
                mime_type=mime_type,
            )

        artifact_path = Path(artifact.path)

        # Multi-file-folder artifacts can't go through ArtifactStorePort.load()
        # (bytes-only contract) -- read a `file` inside the folder, or return
        # a manifest of all its files when no `file` is given.
        if artifact_path.is_dir():
            if file_within:
                try:
                    target = build_isolated_path(artifact_path, file_within)
                except ValueError:
                    return json.dumps(
                        {"status": "error", "message": "access denied: path traversal"}
                    )
                if not target.is_file():
                    return json.dumps(
                        {
                            "status": "error",
                            "message": f"file not found in folder artifact: {file_within}",
                        }
                    )
                return json.dumps(
                    {
                        "status": "ok",
                        "size_bytes": target.stat().st_size,
                        "preview": _decode_preview(target.read_bytes(), mime_type),
                    }
                )
            manifest = sorted(
                (
                    {
                        "path": str(p.relative_to(artifact_path)),
                        "size_bytes": p.stat().st_size,
                    }
                    for p in artifact_path.rglob("*")
                    if p.is_file()
                ),
                key=lambda entry: entry["path"],
            )
            return json.dumps({"status": "ok", "is_directory": True, "files": manifest})

        try:
            content = await store.load(artifact)
        except FileNotFoundError as e:
            return json.dumps({"status": "error", "message": str(e)})

        return json.dumps(
            {
                "status": "ok",
                "size_bytes": len(content),
                "preview": _decode_preview(content, mime_type),
            }
        )

    specs = {
        "artifact.create": ToolSpec(
            name="artifact.create",
            description="Create an artifact (single file or multi-file folder via `files`).",
            parameters={
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                    "files": {
                        "type": "object",
                        "description": "relative_path -> content",
                    },
                    "mime_type": {"type": "string"},
                    "title": {"type": "string"},
                    "type": {
                        "type": "string",
                        "description": "ArtifactType (default: final)",
                    },
                },
            },
        ),
        "artifact.load": ToolSpec(
            name="artifact.load",
            description=(
                "Load a previously created artifact by id or path. For a "
                "multi-file-folder artifact: omit `file` to get a manifest "
                "(list of relative paths + sizes), or set `file` to a "
                "relative path inside the folder to read its content."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "artifact_id": {"type": "string"},
                    "path": {"type": "string"},
                    "file": {
                        "type": "string",
                        "description": "Relative path inside a folder artifact",
                    },
                    "mime_type": {"type": "string"},
                },
            },
        ),
    }
    executors: dict[str, Callable] = {
        "artifact.create": artifact_create_executor,
        "artifact.load": artifact_load_executor,
    }
    return specs, executors
