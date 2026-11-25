"""ArtifactRegistry -- typed, directory-routed artifact index (``.artifacts.json``).

Ported from Aura's ``application/components/workspace/artifact_registry.py``.
Supports both single-file artifacts (``content`` + ``filename``) and
multi-file-folder artifacts (``files``), each routed to the directory implied
by :meth:`ArtifactType.get_directory`.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from swarmline.artifacts.run_root import ArtifactRoot
from swarmline.artifacts.types import Artifact, ArtifactType
from swarmline.path_safety import build_isolated_path

_LIVE_FILE_MAP: dict[str, tuple[ArtifactType, str]] = {
    "goal.md": (ArtifactType.GOAL, "Goal"),
    "plan.md": (ArtifactType.PLAN, "Plan"),
    "todo.md": (ArtifactType.TODO, "Todo"),
    "status.md": (ArtifactType.STATUS, "Status"),
    "sources.md": (ArtifactType.SOURCES, "Sources"),
    "constraints.md": (ArtifactType.CONSTRAINTS, "Constraints"),
}


def _slugify(title: str) -> str:
    """Lowercase, filesystem-safe slug for a folder-artifact directory name."""
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug or "artifact"


class ArtifactRegistry:
    """Index of artifacts created within one :class:`ArtifactRoot`."""

    def __init__(self, root: ArtifactRoot) -> None:
        self.root = root
        self._artifacts: dict[str, Artifact] = {}
        self._index_path = root.path / ".artifacts.json"
        self._load_index()
        self._register_live_files()

    def _load_index(self) -> None:
        if not self._index_path.exists():
            return
        data = json.loads(self._index_path.read_text(encoding="utf-8"))
        for item in data.get("artifacts", []):
            artifact = Artifact(
                id=item["id"],
                type=ArtifactType(item["type"]),
                title=item["title"],
                path=Path(item["path"]),
                mime_type=item.get("mime_type"),
                created_at=datetime.fromisoformat(item["created_at"]),
                version=item.get("version", 1),
                summary=item.get("summary"),
                size_bytes=item.get("size_bytes", 0),
            )
            self._artifacts[artifact.id] = artifact

    def _save_index(self) -> None:
        items = [
            {
                "id": a.id,
                "type": a.type.value,
                "title": a.title,
                "path": str(a.path),
                "mime_type": a.mime_type,
                "created_at": a.created_at.isoformat(),
                "version": a.version,
                "summary": a.summary,
                "size_bytes": a.size_bytes,
            }
            for a in self._artifacts.values()
        ]
        self._index_path.write_text(
            json.dumps({"artifacts": items}, indent=2), encoding="utf-8"
        )

    def _register_live_files(self) -> None:
        for filename, (artifact_type, title) in _LIVE_FILE_MAP.items():
            file_path = self.root.path / filename
            if not file_path.exists() or self._find_by_path(file_path) is not None:
                continue
            artifact = Artifact(
                id=f"live_{filename.removesuffix('.md')}",
                type=artifact_type,
                title=title,
                path=file_path,
                mime_type="text/markdown",
                size_bytes=file_path.stat().st_size,
            )
            self._artifacts[artifact.id] = artifact

    def _find_by_path(self, path: Path) -> Artifact | None:
        for artifact in self._artifacts.values():
            if artifact.path == path:
                return artifact
        return None

    def create(
        self,
        type: ArtifactType,
        title: str,
        content: str | bytes | None = None,
        filename: str | None = None,
        files: dict[str, str | bytes] | None = None,
        mime_type: str | None = None,
        summary: str | None = None,
    ) -> Artifact:
        """Create an artifact: single file (``content``+``filename``) or folder (``files``).

        Exactly one of ``files`` or (``content`` + ``filename``) must be given.

        Raises:
            ValueError: neither/both creation modes are supplied.
        """
        if files:
            return self._create_folder(type, title, files, mime_type, summary)
        if content is not None and filename:
            return self._create_file(type, title, content, filename, mime_type, summary)
        raise ValueError("create() requires either `files` or `content` + `filename`")

    def _type_directory(self, type: ArtifactType) -> Path:
        directory = type.get_directory()
        dir_path = self.root.path / directory if directory else self.root.path
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def _create_file(
        self,
        type: ArtifactType,
        title: str,
        content: str | bytes,
        filename: str,
        mime_type: str | None,
        summary: str | None,
    ) -> Artifact:
        dir_path = self._type_directory(type)
        file_path = build_isolated_path(dir_path, filename)
        if isinstance(content, bytes):
            file_path.write_bytes(content)
        else:
            file_path.write_text(content, encoding="utf-8")

        artifact = Artifact(
            id=f"art_{uuid.uuid4().hex[:12]}",
            type=type,
            title=title,
            path=file_path,
            mime_type=mime_type,
            summary=summary,
            size_bytes=file_path.stat().st_size,
        )
        self._artifacts[artifact.id] = artifact
        self._save_index()
        return artifact

    def _create_folder(
        self,
        type: ArtifactType,
        title: str,
        files: dict[str, str | bytes],
        mime_type: str | None,
        summary: str | None,
    ) -> Artifact:
        dir_path = self._type_directory(type)
        artifact_id = f"art_{uuid.uuid4().hex[:12]}"
        folder_path = dir_path / f"{artifact_id}_{_slugify(title)}"
        folder_path.mkdir(parents=True, exist_ok=True)

        total_size = 0
        for relative_path, data in files.items():
            file_path = build_isolated_path(folder_path, relative_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                file_path.write_bytes(data)
                total_size += len(data)
            else:
                file_path.write_text(data, encoding="utf-8")
                total_size += len(data.encode("utf-8"))

        artifact = Artifact(
            id=artifact_id,
            type=type,
            title=title,
            path=folder_path,
            mime_type=mime_type,
            summary=summary,
            size_bytes=total_size,
        )
        self._artifacts[artifact.id] = artifact
        self._save_index()
        return artifact

    def get(self, artifact_id: str) -> Artifact | None:
        """Look up an artifact by id."""
        return self._artifacts.get(artifact_id)

    def get_live(self) -> list[Artifact]:
        """All live (overwritten-in-place) artifacts."""
        return [a for a in self._artifacts.values() if a.is_live()]

    def get_immutable(self) -> list[Artifact]:
        """All immutable (append-only) artifacts."""
        return [a for a in self._artifacts.values() if a.is_immutable()]

    def get_by_type(self, artifact_type: ArtifactType) -> list[Artifact]:
        """All artifacts of the given type."""
        return [a for a in self._artifacts.values() if a.type == artifact_type]

    def list_all(self) -> list[Artifact]:
        """All artifacts in the registry."""
        return list(self._artifacts.values())
