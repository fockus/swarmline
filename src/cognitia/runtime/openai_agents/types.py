"""Domain types for OpenAI Agents Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OpenAIAgentsConfig:
    """Configuration for OpenAI Agents Runtime.

    Describes how to create an OpenAI Agent and optionally
    attach Codex as an MCP server.
    """

    model: str = "gpt-4.1"
    codex_enabled: bool = False
    codex_sandbox: str = "network-off"
    codex_approval_policy: str = "suggest"
    max_turns: int = 25
    env: dict[str, str] = field(default_factory=dict)
