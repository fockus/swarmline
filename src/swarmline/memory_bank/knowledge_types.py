"""Universal knowledge bank domain types -- domain-agnostic structured records.

Types for organizing, tagging, and searching knowledge across any domain
(research, business, education, engineering). Inspired by structured
memory bank patterns but without code-development specifics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

DocumentKind = Literal[
    "status",
    "plan",
    "checklist",
    "research",
    "backlog",
    "progress",
    "lesson",
    "note",
    "report",
    "experiment",
]


@dataclass(frozen=True)
class DocumentMeta:
    """YAML frontmatter metadata for any knowledge document."""

    kind: DocumentKind
    tags: tuple[str, ...] = ()
    importance: Literal["high", "medium", "low"] = "medium"
    created: str = ""
    updated: str = ""
    related: tuple[str, ...] = ()
    custom: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeEntry:
    """A document in the knowledge bank with parsed metadata."""

    path: str
    meta: DocumentMeta
    content: str
    size_bytes: int = 0


@dataclass(frozen=True)
class IndexEntry:
    """Lightweight entry for the search index (no full content)."""

    path: str
    kind: DocumentKind
    tags: tuple[str, ...] = ()
    importance: str = "medium"
    summary: str = ""
    updated: str = ""


@dataclass(frozen=True)
class KnowledgeIndex:
    """Full index of the knowledge bank."""

    version: int = 1
    updated: str = ""
    entries: tuple[IndexEntry, ...] = ()


@dataclass(frozen=True)
class ChecklistItem:
    """A task item in a checklist."""

    text: str
    done: bool = False
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class QualityCriterion:
    """A generic quality criterion for verification."""

    name: str
    description: str = ""
    met: bool = False
    evidence: str = ""


@dataclass(frozen=True)
class ExperimentRecord:
    """A structured experiment record (domain-agnostic)."""

    id: str
    hypothesis: str
    method: str = ""
    result: str = ""
    outcome: Literal["confirmed", "rejected", "inconclusive", "pending"] = "pending"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class LearnedPattern:
    """A learned pattern or antipattern (domain-agnostic)."""

    id: str
    pattern: str
    context: str = ""
    recommendation: str = ""
    kind: Literal["pattern", "antipattern", "heuristic"] = "pattern"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeBankConfig:
    """Configuration for the knowledge bank layer."""

    enabled: bool = False
    core_documents: tuple[str, ...] = (
        "STATUS.md",
        "plan.md",
        "checklist.md",
        "RESEARCH.md",
        "BACKLOG.md",
        "progress.md",
        "lessons.md",
    )
    directories: tuple[str, ...] = ("plans", "notes", "reports", "experiments")
    auto_index: bool = True
    verification_enabled: bool = False
