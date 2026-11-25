"""Pure value types for DefaultContextBuilder.

Split out of ``builder.py`` to respect its file-size ceiling (Stage P1,
artifacts ``available_files`` context injection added a new layer). Re-exported
from ``builder.py`` for backward compatibility -- existing imports like
``from swarmline.context.builder import ContextInput`` keep working unchanged.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from swarmline.context.budget import ContextBudget


def compute_prompt_hash(prompt: str) -> str:
    """Compute the SHA256 hash of system_prompt (R-300, §12.1)."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ContextInput:
    """Input data for context assembly."""

    user_id: str
    topic_id: str
    role_id: str
    user_text: str
    active_skill_ids: list[str]
    budget: ContextBudget = field(default_factory=ContextBudget)


@dataclass(frozen=True)
class BuiltContext:
    """Result of context assembly."""

    system_prompt: str
    prompt_hash: str  # SHA256 hash of system_prompt (§12.1)
    tool_budget: int  # how many tools can be given to the context
    truncated_packs: list[str]  # which packets were truncated
    notes: dict[str, str] = field(default_factory=dict)
