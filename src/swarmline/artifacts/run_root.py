"""ArtifactRoot -- per-run root directory for artifacts/registry/live files.

Ported (trimmed) from Aura's ``RunWorkspace``: this stage only needs the
directory-structure + sub-agent inheritance parts (``create_child`` /
``read_parent_file``); goal/plan/todo templating stays with swarmline's own
``todo`` capability and is out of scope here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from swarmline.path_safety import build_isolated_path, validate_namespace_segment

#: Standard artifact-type directories created eagerly under every root.
REQUIRED_DIRS: tuple[str, ...] = (
    "tool_outputs",
    "notes",
    "snapshots/web",
    "data/raw",
    "data/clean",
    "code/runs",
    "charts",
    "drafts",
    "final",
)


@dataclass(frozen=True, slots=True)
class ArtifactRoot:
    """Root directory for one run's artifacts.

    ``parent`` is set on child roots created via :meth:`create_child`;
    :meth:`read_parent_file` grants read-only, traversal-guarded access to the
    parent's files so artifacts flow DOWN to sub-agents, never up.
    """

    path: Path
    parent: Path | None = None

    @classmethod
    def create(cls, base_path: str | Path, run_id: str | None = None) -> ArtifactRoot:
        """Create a new artifact root with the standard directory layout.

        Raises:
            ValueError: ``run_id`` is not a single safe path segment (contains
                ``/``, ``\\``, or ``..`` -- see ``validate_namespace_segment``).
        """
        run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        validate_namespace_segment(run_id, "run_id")
        # MAJOR 2 fix: resolve here (once) so `.path` is always absolute --
        # tools that do `path.relative_to(root.path)` (build_isolated_path
        # always resolves) must never see a mismatched relative `root.path`.
        root_path = (Path(base_path) / run_id).resolve()
        for sub in REQUIRED_DIRS:
            (root_path / sub).mkdir(parents=True, exist_ok=True)
        return cls(path=root_path)

    def create_child(self, child_id: str | None = None) -> ArtifactRoot:
        """Create an isolated child root (sub-agent) under ``children/``.

        Raises:
            ValueError: ``child_id`` is not a single safe path segment.
        """
        child_id = child_id or f"run_{uuid.uuid4().hex[:12]}"
        validate_namespace_segment(child_id, "child_id")
        child_path = (self.path / "children" / child_id).resolve()
        for sub in REQUIRED_DIRS:
            (child_path / sub).mkdir(parents=True, exist_ok=True)
        return ArtifactRoot(path=child_path, parent=self.path.resolve())

    def read_parent_file(self, relative_path: str) -> str | None:
        """Read-only access to a file in the parent root.

        Returns ``None`` when there is no parent, the path escapes the parent
        root (path-traversal attempt), or the file does not exist.
        """
        if self.parent is None:
            return None
        try:
            file_path = build_isolated_path(self.parent, relative_path)
        except ValueError:
            return None
        if not file_path.is_file():
            return None
        return file_path.read_text(encoding="utf-8")
