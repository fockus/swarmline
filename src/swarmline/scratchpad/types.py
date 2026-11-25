"""Scratchpad data types — ephemeral within-run working memory entries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class ScratchpadEntry:
    """A single scratchpad entry.

    Immutable — providers produce new instances on update.
    """

    key: str
    content: str
    tags: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
