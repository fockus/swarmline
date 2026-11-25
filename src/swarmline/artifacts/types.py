"""Pure domain types for the artifacts capability -- zero external deps.

Ported from Aura's RunWorkspace artifact domain (``domain/models/artifacts.py``).
Two artifact classes:

- LIVE (overwritten, versioned): goal, plan, todo, status, sources, constraints.
- IMMUTABLE (append-only): tool_output, step_note, web_snapshot, raw_data, ...

All dataclasses are frozen (no mutation) per project convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Directory routing (kept outside the enum body so it stays a plain mapping)
# ---------------------------------------------------------------------------

_LIVE_TYPES: frozenset[str] = frozenset(
    {"goal", "plan", "todo", "status", "sources", "constraints"}
)

_DIRECTORY_MAP: dict[str, str] = {
    # Live -> workspace root
    "goal": "",
    "plan": "",
    "todo": "",
    "status": "",
    "sources": "",
    "constraints": "",
    # Immutable -> subdirectories
    "tool_output": "tool_outputs",
    "step_note": "notes",
    "web_snapshot": "snapshots/web",
    "search_result": "tool_outputs",
    "raw_data": "data/raw",
    "clean_data": "data/clean",
    "analysis": "tool_outputs",
    "code_script": "code",
    "code_output": "code/runs",
    "chart": "charts",
    "draft": "drafts",
    "final": "final",
    "subagent_result": "tool_outputs",
}


class ArtifactType(StrEnum):
    """Artifact type: classifies live-vs-immutable and its on-disk directory."""

    # Live (overwritten) -- root of the workspace
    GOAL = "goal"
    PLAN = "plan"
    TODO = "todo"
    STATUS = "status"
    SOURCES = "sources"
    CONSTRAINTS = "constraints"

    # Immutable (append-only)
    TOOL_OUTPUT = "tool_output"
    STEP_NOTE = "step_note"
    WEB_SNAPSHOT = "web_snapshot"
    SEARCH_RESULT = "search_result"
    RAW_DATA = "raw_data"
    CLEAN_DATA = "clean_data"
    ANALYSIS = "analysis"
    CODE_SCRIPT = "code_script"
    CODE_OUTPUT = "code_output"
    CHART = "chart"
    DRAFT = "draft"
    FINAL = "final"
    SUBAGENT_RESULT = "subagent_result"

    def is_live(self) -> bool:
        """True when this type is overwritten in place (not append-only)."""
        return self.value in _LIVE_TYPES

    def is_immutable(self) -> bool:
        """True when this type is append-only."""
        return not self.is_live()

    def get_directory(self) -> str:
        """Relative directory this type is stored under (``""`` = workspace root)."""
        return _DIRECTORY_MAP.get(self.value, "")


@dataclass(frozen=True, slots=True)
class Artifact:
    """A tracked artifact: a single file, or the root of a multi-file folder."""

    id: str
    type: ArtifactType
    title: str
    path: Path
    mime_type: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    summary: str | None = None
    size_bytes: int = 0

    def is_live(self) -> bool:
        """True when the artifact's type is live (overwritten in place)."""
        return self.type.is_live()

    def is_immutable(self) -> bool:
        """True when the artifact's type is append-only."""
        return self.type.is_immutable()


@dataclass(frozen=True, slots=True)
class FileEntry:
    """One row of the human/LLM-readable :class:`FileRegistry` (``.registry.md``)."""

    path: str
    description: str
    category: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    size_bytes: int = 0


@dataclass(frozen=True, slots=True)
class StepJournalEntry:
    """One append-only entry of the :class:`~swarmline.artifacts.step_journal.StepJournal`."""

    step_id: int
    task: str
    tool_name: str
    tool_args: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: str | None = None
    summary: str | None = None
    raw_output_path: str | None = None
    artifacts_created: tuple[str, ...] = ()
    mutations: tuple[str, ...] = ()
    notes_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return {
            "step_id": self.step_id,
            "task": self.task,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "summary": self.summary,
            "raw_output_path": self.raw_output_path,
            "artifacts_created": list(self.artifacts_created),
            "mutations": list(self.mutations),
            "notes_path": self.notes_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepJournalEntry:
        """Deserialize from :meth:`to_dict` output (or any compatible dict)."""
        timestamp = data.get("timestamp")
        return cls(
            step_id=data["step_id"],
            task=data["task"],
            tool_name=data["tool_name"],
            tool_args=data.get("tool_args", {}),
            timestamp=datetime.fromisoformat(timestamp)
            if timestamp
            else datetime.now(UTC),
            status=data.get("status"),
            summary=data.get("summary"),
            raw_output_path=data.get("raw_output_path"),
            artifacts_created=tuple(data.get("artifacts_created", ())),
            mutations=tuple(data.get("mutations", ())),
            notes_path=data.get("notes_path"),
        )
