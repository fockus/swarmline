"""OSS capability discovery types — zero product coupling.

REQ-OSS-051: no AccessContext / UnitOfWork / tenant / workspace /
FastAPI / SQLAlchemy. Generic str ids. Covers TOOL / MCP / SKILL / WORKFLOW.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CapabilityKind(StrEnum):
    """Kind of capability — one of four source types."""

    TOOL = "tool"
    MCP = "mcp"
    SKILL = "skill"
    WORKFLOW = "workflow"


class RiskLevel(StrEnum):
    """Risk classification for a capability."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(slots=True, frozen=True)
class CapabilityDoc:
    """Unified capability document (frozen, immutable).

    Represents a single capability of any kind (tool, MCP entry, skill,
    or workflow). Uses generic str ids — no tenant / workspace coupling.
    Policy decisions are made by injected callables at the service layer.
    """

    # --- identity ---
    capability_id: str  # e.g. "tool:web_search", "skill:code-review"
    kind: CapabilityKind
    source: str  # e.g. "local", "mcp:github", "yaml"

    # --- human-readable ---
    name: str
    description: str

    # --- schema & examples ---
    input_schema: dict[str, object] | None
    examples: list[str]

    # --- discovery metadata ---
    tags: list[str]
    required_capabilities: list[str]  # e.g. ["mcp", "filesystem"]
    runtime_allow: list[str]  # e.g. ["thin", "claude_sdk"]
    allowed_tools: list[str]

    # --- quality hints ---
    risk_level: RiskLevel
    cost_hint: str  # "cheap" | "normal" | "expensive"
    latency_hint: str  # "fast" | "normal" | "slow"

    # --- content ---
    content_md: str  # body text (SKILL.md body or equivalent)
    enabled: bool

    # --- optional / extensible ---
    roles_allow: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.capability_id.strip():
            raise ValueError("CapabilityDoc capability_id must not be blank")
        if not self.name.strip():
            raise ValueError("CapabilityDoc name must not be blank")
        if not self.runtime_allow:
            raise ValueError("CapabilityDoc runtime_allow must not be empty")
