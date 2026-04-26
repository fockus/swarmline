"""Model Policy module."""

from __future__ import annotations

from dataclasses import dataclass, field


_OPUS_KEYWORDS: tuple[str, ...] = (
    "план",
    "стратеги",
    "пошагов",
    "дорожн",
    "разбер",
    "сравни",
)


@dataclass
class ModelPolicy:
    """Model Policy implementation."""

    default_model: str = "sonnet"
    escalation_model: str = "opus"
    escalate_on_tool_failures: int = 3
    escalate_roles: set[str] = field(default_factory=set)
    min_skills_for_escalation: int = 2

    def select(self, role_id: str, tool_failure_count: int = 0) -> str:
        """Select."""
        return self.select_for_turn(
            role_id=role_id,
            user_text="",
            tool_failure_count=tool_failure_count,
        )

    def select_for_turn(
        self,
        role_id: str,
        user_text: str,
        active_skill_count: int = 0,
        tool_failure_count: int = 0,
    ) -> str:
        """Select for turn."""

        if role_id in self.escalate_roles:
            return self.escalation_model

        if tool_failure_count >= self.escalate_on_tool_failures:
            return self.escalation_model

        # 3. Multi-skill
        if active_skill_count >= self.min_skills_for_escalation:
            return self.escalation_model

        # 4. Keyword triggers
        text_lower = user_text.lower()
        for kw in _OPUS_KEYWORDS:
            if kw in text_lower:
                return self.escalation_model

        return self.default_model
