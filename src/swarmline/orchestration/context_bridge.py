"""ContextBridge — structured context transfer from parent agent to subagent."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContextBridge:
    """Immutable context snapshot passed from parent agent to subagent.

    Carries the parent's goal, progress, accumulated findings,
    and which tools the subagent may inherit.
    """

    parent_goal: str
    parent_progress: str
    parent_findings: list[str] = field(default_factory=list)
    inherited_tools: list[str] = field(default_factory=list)
    max_turns: int = 10


class ContextBridgeBuilder:
    """Static factory and formatter for ContextBridge."""

    @staticmethod
    def from_agent_state(
        goal: str,
        progress: str,
        findings: list[str],
        tools: list[str],
        max_turns: int = 10,
    ) -> ContextBridge:
        """Create a ContextBridge from current agent state."""
        return ContextBridge(
            parent_goal=goal,
            parent_progress=progress,
            parent_findings=list(findings),
            inherited_tools=list(tools),
            max_turns=max_turns,
        )

    @staticmethod
    def format_for_prompt(bridge: ContextBridge) -> str:
        """Format a ContextBridge as a readable prompt section for the subagent."""
        lines = [
            "## Parent Context",
            f"**Goal:** {bridge.parent_goal}",
            f"**Progress:** {bridge.parent_progress}",
        ]
        if bridge.parent_findings:
            lines.append("**Findings:**")
            for finding in bridge.parent_findings:
                lines.append(f"- {finding}")
        if bridge.inherited_tools:
            lines.append(f"**Available tools:** {', '.join(bridge.inherited_tools)}")
        lines.append(f"**Turn budget:** {bridge.max_turns}")
        return "\n".join(lines)
