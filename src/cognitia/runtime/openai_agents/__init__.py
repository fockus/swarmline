"""OpenAI Agents Runtime - wrapper around OpenAI Agents SDK (openai-agents).

Provides AgentRuntime implementation backed by the OpenAI Agents SDK,
with optional Codex MCP server integration.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["OpenAIAgentsRuntime"]

_OPTIONAL_EXPORTS: dict[str, tuple[str, str, str]] = {
    "OpenAIAgentsRuntime": (
        "cognitia.runtime.openai_agents.runtime",
        "OpenAIAgentsRuntime",
        "Install openai-agents to use OpenAIAgentsRuntime: pip install cognitia[openai-agents]",
    ),
}


def __getattr__(name: str) -> Any:
    optional = _OPTIONAL_EXPORTS.get(name)
    if optional is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name, hint = optional
    try:
        module = import_module(module_name)
        return getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        raise ImportError(f"{attr_name} is unavailable. {hint}") from exc
