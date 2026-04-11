"""Sdk Query module."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from claude_agent_sdk import query as _sdk_query
from claude_agent_sdk.types import StreamEvent as SdkStreamEvent

from swarmline.runtime.adapter import (
    StreamEvent,
    _extract_partial_text_delta,
    _format_system_message,
)


@dataclass
class QueryResult:
    """Query Result result."""

    text: str = ""
    session_id: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    structured_output: Any = None


def _build_options(
    *,
    system_prompt: str | None,
    model: str | None,
    permission_mode: str,
    cwd: str | None,
    output_format: dict[str, Any] | None,
    max_turns: int | None,
    mcp_servers: dict[str, Any] | None,
    allowed_tools: list[str] | None,
    hooks: dict[str, list[Any]] | None,
    max_budget_usd: float | None,
    fallback_model: str | None,
    betas: list[str] | None,
    env: dict[str, str] | None,
    setting_sources: list[str] | None,
    include_partial_messages: bool = False,
) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        permission_mode=cast(Any, permission_mode),
        cwd=cwd,
        output_format=output_format,
        max_turns=max_turns,
        mcp_servers=mcp_servers or {},
        allowed_tools=allowed_tools or [],
        hooks=cast(Any, hooks),
        max_budget_usd=max_budget_usd,
        fallback_model=fallback_model,
        betas=cast(Any, betas or []),
        env=env or {},
        setting_sources=cast(Any, setting_sources),
        include_partial_messages=include_partial_messages,
    )


def _extract_text_blocks(message: AssistantMessage) -> str:
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            parts.append(block.text)
    return "".join(parts)


def _missing_final_result_error() -> RuntimeError:
    return RuntimeError("SDK query completed without final ResultMessage")


async def one_shot_query(
    prompt: str,
    *,
    system_prompt: str | None = None,
    model: str | None = None,
    permission_mode: str = "bypassPermissions",
    cwd: str | None = None,
    output_format: dict[str, Any] | None = None,
    max_turns: int | None = None,
    mcp_servers: dict[str, Any] | None = None,
    allowed_tools: list[str] | None = None,
    hooks: dict[str, list[Any]] | None = None,
    max_budget_usd: float | None = None,
    fallback_model: str | None = None,
    betas: list[str] | None = None,
    env: dict[str, str] | None = None,
    setting_sources: list[str] | None = None,
) -> QueryResult:
    """One shot query."""
    options = _build_options(
        system_prompt=system_prompt,
        model=model,
        permission_mode=permission_mode,
        cwd=cwd,
        output_format=output_format,
        max_turns=max_turns,
        mcp_servers=mcp_servers,
        allowed_tools=allowed_tools,
        hooks=hooks,
        max_budget_usd=max_budget_usd,
        fallback_model=fallback_model,
        betas=betas,
        env=env,
        setting_sources=setting_sources,
    )

    full_text = ""
    result = QueryResult()
    saw_result_message = False

    async for message in _sdk_query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            full_text += _extract_text_blocks(message)
        elif isinstance(message, ResultMessage):
            saw_result_message = True
            result.session_id = getattr(message, "session_id", None)
            result.total_cost_usd = getattr(message, "total_cost_usd", None)
            result.usage = getattr(message, "usage", None)
            result.structured_output = getattr(message, "structured_output", None)

    if not saw_result_message:
        raise _missing_final_result_error()

    result.text = full_text
    return result


async def stream_one_shot_query(
    prompt: str,
    *,
    system_prompt: str | None = None,
    model: str | None = None,
    permission_mode: str = "bypassPermissions",
    cwd: str | None = None,
    output_format: dict[str, Any] | None = None,
    max_turns: int | None = None,
    mcp_servers: dict[str, Any] | None = None,
    allowed_tools: list[str] | None = None,
    hooks: dict[str, list[Any]] | None = None,
    max_budget_usd: float | None = None,
    fallback_model: str | None = None,
    betas: list[str] | None = None,
    env: dict[str, str] | None = None,
    setting_sources: list[str] | None = None,
    include_partial_messages: bool = False,
) -> AsyncIterator[StreamEvent]:
    """Stream one shot query."""
    options = _build_options(
        system_prompt=system_prompt,
        model=model,
        permission_mode=permission_mode,
        cwd=cwd,
        output_format=output_format,
        max_turns=max_turns,
        mcp_servers=mcp_servers,
        allowed_tools=allowed_tools,
        hooks=hooks,
        max_budget_usd=max_budget_usd,
        fallback_model=fallback_model,
        betas=betas,
        env=env,
        setting_sources=setting_sources,
        include_partial_messages=include_partial_messages,
    )

    full_text = ""
    result_meta: dict[str, Any] = {}
    saw_partial_text = False
    saw_result_message = False

    async for message in _sdk_query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    if not saw_partial_text:
                        full_text += block.text
                        yield StreamEvent(type="text_delta", text=block.text)
                elif isinstance(block, ThinkingBlock):
                    continue
                elif isinstance(block, ToolUseBlock):
                    yield StreamEvent(
                        type="tool_use_start",
                        tool_name=block.name,
                        tool_input=block.input,
                    )
                elif isinstance(block, ToolResultBlock):
                    yield StreamEvent(
                        type="tool_use_result",
                        tool_result=str(getattr(block, "content", "")),
                    )
        elif isinstance(message, SystemMessage):
            status_text = _format_system_message(message)
            if status_text:
                yield StreamEvent(type="status", text=status_text)
        elif isinstance(message, ResultMessage):
            saw_result_message = True
            result_meta = {
                "session_id": getattr(message, "session_id", None),
                "total_cost_usd": getattr(message, "total_cost_usd", None),
                "usage": getattr(message, "usage", None),
                "structured_output": getattr(message, "structured_output", None),
            }
        elif isinstance(message, SdkStreamEvent) and include_partial_messages:
            partial_text = _extract_partial_text_delta(message)
            if partial_text:
                saw_partial_text = True
                full_text += partial_text
                yield StreamEvent(type="text_delta", text=partial_text)

    if not saw_result_message:
        yield StreamEvent(
            type="error",
            text="SDK query completed without final ResultMessage",
        )
        return

    yield StreamEvent(
        type="done",
        text=full_text,
        is_final=True,
        session_id=result_meta.get("session_id"),
        total_cost_usd=result_meta.get("total_cost_usd"),
        usage=result_meta.get("usage"),
        structured_output=result_meta.get("structured_output"),
    )
