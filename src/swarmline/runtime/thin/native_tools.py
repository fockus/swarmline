"""Native tool calling types and protocol for provider-specific tool APIs.

When use_native_tools=True, LLM providers receive tools via their native API
instead of JSON-in-text prompting. This module defines the shared types and
converter functions for Anthropic, OpenAI, and Google Gemini formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from swarmline.domain_types import ToolSpec


@dataclass(frozen=True)
class NativeToolCall:
    """A single tool call from provider's native response."""

    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NativeToolCallResult:
    """Result from native tool calling API."""

    text: str = ""
    tool_calls: tuple[NativeToolCall, ...] = ()
    stop_reason: str = "end_turn"


@runtime_checkable
class NativeToolCallAdapter(Protocol):
    """Adapter that supports native tool calling API."""

    async def call_with_tools(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> NativeToolCallResult: ...


def toolspecs_to_anthropic(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    """Convert ToolSpec list to Anthropic tool format."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.parameters,
        }
        for spec in specs
    ]


def toolspecs_to_openai(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    """Convert ToolSpec list to OpenAI tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in specs
    ]


def toolspecs_to_google(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    """Convert ToolSpec list to Google Gemini tool format."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        }
        for spec in specs
    ]
