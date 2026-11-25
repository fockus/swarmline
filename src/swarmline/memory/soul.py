"""Agent soul configuration and typed user-knowledge entries.

AgentSoulConfig: frozen persona/tone/rules config with a prompt-block renderer.
UserKnowledge:   frozen per-user knowledge entry with confidence score.
KnowledgeCategory: StrEnum classifying knowledge type.

All ids are plain ``str``. Zero product (tenant/workspace/FastAPI/SQLAlchemy) coupling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast


class KnowledgeCategory(StrEnum):
    """Semantic category for a :class:`UserKnowledge` entry."""

    PREFERENCE = "preference"
    PATTERN = "pattern"
    CONTEXT = "context"
    FACT = "fact"


def _now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class UserKnowledge:
    """A single typed knowledge entry an agent holds about a user.

    Args:
        agent_id:   Plain str identifying the agent that recorded this entry.
        user_id:    Plain str identifying the user this knowledge concerns.
        category:   Semantic category (:class:`KnowledgeCategory`).
        key:        Non-empty string key (e.g. ``"preferred_language"``).
        value:      Non-empty string value (e.g. ``"Python"``).
        confidence: Float in ``[0.0, 1.0]``. Defaults to ``1.0``.
        created_at: UTC timestamp of creation; defaults to now.
        updated_at: UTC timestamp of last update; defaults to now.
    """

    agent_id: str
    user_id: str
    category: KnowledgeCategory
    key: str
    value: str
    confidence: float = 1.0
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("UserKnowledge.key must not be blank")
        if not self.value.strip():
            raise ValueError("UserKnowledge.value must not be blank")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"UserKnowledge.confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        # Coerce raw string to enum if necessary
        if not isinstance(self.category, KnowledgeCategory):
            try:
                object.__setattr__(self, "category", KnowledgeCategory(self.category))
            except ValueError:
                valid = [c.value for c in KnowledgeCategory]
                raise ValueError(
                    f"Invalid category {self.category!r}. Valid values: {valid}"
                ) from None


@dataclass(frozen=True)
class AgentSoulConfig:
    """Persona configuration that an agent can inject into its system prompt.

    The ``to_prompt_block()`` method renders a compact, human-readable block
    suitable for prepending to an LLM system prompt.  The format is deliberately
    simple so downstream code can wrap it in any XML/markdown framing it needs.

    Args:
        personality:        Non-empty description of the agent's character.
        tone:               Communication tone. Defaults to ``"neutral"``.
        behavior_rules:     Tuple of imperative rule strings (may be empty).
        persona_description: Optional free-form narrative description.
    """

    personality: str
    tone: str = "neutral"
    behavior_rules: tuple[str, ...] = ()
    persona_description: str = ""

    def __post_init__(self) -> None:
        if not self.personality.strip():
            raise ValueError("AgentSoulConfig.personality must not be blank")

    @classmethod
    def from_profile(cls, profile: dict[str, object]) -> AgentSoulConfig | None:
        """Extract soul config from an agent profile dict.

        Returns ``None`` if the ``"soul"`` key is absent or unusable.
        """
        raw = profile.get("soul")
        if not isinstance(raw, dict):
            return None
        # cast so strict type-checkers (ty) can resolve dict.get() overloads
        raw_dict = cast(dict[str, object], raw)
        personality = str(raw_dict.get("personality", "")).strip()
        if not personality:
            return None
        tone = str(raw_dict.get("tone", "neutral")).strip() or "neutral"
        raw_rules = raw_dict.get("behavior_rules")
        rules: tuple[str, ...] = (
            tuple(str(r) for r in raw_rules)
            if isinstance(raw_rules, (list, tuple))
            else ()
        )
        persona = str(raw_dict.get("persona_description", "")).strip()
        return cls(
            personality=personality,
            tone=tone,
            behavior_rules=rules,
            persona_description=persona,
        )

    def to_prompt_block(self) -> str:
        """Render soul config as a compact prompt block.

        Example output::

            [Agent Personality]
            Personality: curious researcher
            Tone: friendly
            Rules:
            - never lie
            - be concise
            You are a wise guide who helps users navigate complex topics.
        """
        lines: list[str] = [
            "[Agent Personality]",
            f"Personality: {self.personality}",
            f"Tone: {self.tone}",
        ]
        if self.behavior_rules:
            lines.append("Rules:")
            for rule in self.behavior_rules:
                lines.append(f"- {rule}")
        if self.persona_description:
            lines.append(self.persona_description)
        return "\n".join(lines)
