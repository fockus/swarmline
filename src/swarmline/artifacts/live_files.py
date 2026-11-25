"""LiveFilesManager -- versioned CRUD for live files (goal/plan/todo/status/...).

Ported from Aura's ``application/components/workspace/live_files.py``. Old
versions are kept under ``.versions/{name}_v{NNN}.md`` so a rollback
(``get_version``) is always possible.
"""

from __future__ import annotations

from swarmline.artifacts.run_root import ArtifactRoot

_LIVE_BASE_NAMES: tuple[str, ...] = (
    "todo",
    "status",
    "plan",
    "sources",
    "goal",
    "constraints",
)


class LiveFilesManager:
    """Versioned read/write access to a root's live files."""

    def __init__(self, root: ArtifactRoot) -> None:
        self.root = root
        self._versions_dir = root.path / ".versions"
        self._versions_dir.mkdir(exist_ok=True)
        self._version_counters: dict[str, int] = {}
        self._load_version_counters()

    def _load_version_counters(self) -> None:
        for base_name in _LIVE_BASE_NAMES:
            existing = list(self._versions_dir.glob(f"{base_name}_v*.md"))
            max_version = 0
            for f in existing:
                try:
                    max_version = max(max_version, int(f.stem.rsplit("_v", 1)[-1]))
                except (ValueError, IndexError):
                    continue
            self._version_counters[base_name] = max_version

    def _save_version(self, filename: str, content: str) -> int:
        base_name = filename.removesuffix(".md")
        self._version_counters[base_name] = self._version_counters.get(base_name, 0) + 1
        version = self._version_counters[base_name]
        version_path = self._versions_dir / f"{base_name}_v{version:03d}.md"
        version_path.write_text(content, encoding="utf-8")
        return version

    def update_file(self, filename: str, new_content: str) -> int:
        """Write ``new_content`` to ``filename``, versioning the prior content."""
        file_path = self.root.path / filename
        version = 0
        if file_path.exists():
            version = self._save_version(
                filename, file_path.read_text(encoding="utf-8")
            )
        file_path.write_text(new_content, encoding="utf-8")
        return version

    def update_todo(self, content: str) -> int:
        """Overwrite ``todo.md``, versioning the previous content. Returns the saved version."""
        return self.update_file("todo.md", content)

    def update_status(self, content: str) -> int:
        """Overwrite ``status.md``, versioning the previous content."""
        return self.update_file("status.md", content)

    def update_plan(self, content: str) -> int:
        """Overwrite ``plan.md``, versioning the previous content."""
        return self.update_file("plan.md", content)

    def update_sources(self, content: str) -> int:
        """Overwrite ``sources.md``, versioning the previous content."""
        return self.update_file("sources.md", content)

    def update_goal(self, content: str) -> int:
        """Overwrite ``goal.md``, versioning the previous content."""
        return self.update_file("goal.md", content)

    def update_constraints(self, content: str) -> int:
        """Overwrite ``constraints.md``, versioning the previous content."""
        return self.update_file("constraints.md", content)

    def get_version_history(self, filename: str) -> list[dict[str, str | int]]:
        """List saved versions (version/path/timestamp) for ``filename``, oldest first."""
        base_name = filename.removesuffix(".md")
        history: list[dict[str, str | int]] = []
        for f in sorted(self._versions_dir.glob(f"{base_name}_v*.md")):
            try:
                version = int(f.stem.rsplit("_v", 1)[-1])
            except (ValueError, IndexError):
                continue
            history.append({"version": version, "path": str(f)})
        return history

    def get_version(self, filename: str, version: int) -> str | None:
        """Return the saved content of ``filename`` at ``version``, or None if missing."""
        base_name = filename.removesuffix(".md")
        version_path = self._versions_dir / f"{base_name}_v{version:03d}.md"
        if version_path.exists():
            return version_path.read_text(encoding="utf-8")
        return None
