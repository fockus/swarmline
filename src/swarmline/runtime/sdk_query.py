"""Sdk Query module.

One-shot ``claude_agent_sdk`` query wrappers (``one_shot_query`` /
``stream_one_shot_query``), used by ``Agent.query()``/``Agent.stream()``.

Parity guarantee (I-099): ``_build_options`` resolves every option it shares
with the conversation path (``ClaudeOptionsBuilder.build`` in
``runtime/options_builder.py``) using the *same* normalization —
``thinking``/``max_thinking_tokens`` are merged via the shared
``_resolve_thinking`` helper, ``sandbox`` is passed through unchanged. A given
``AgentConfig`` therefore produces the same ``ClaudeAgentOptions`` regardless
of whether the facade dispatches through the one-shot path (this module) or
the multi-turn conversation path.
"""

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
    _extract_partial_thinking_delta,
    _format_system_message,
)
from swarmline.runtime.options_builder import _resolve_thinking


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
    can_use_tool: Any | None = None,
    agents: dict[str, Any] | None = None,
    resume: str | None = None,
    fork_session: bool = False,
    thinking: dict[str, Any] | None = None,
    max_thinking_tokens: int | None = None,
    sandbox: dict[str, Any] | None = None,
) -> ClaudeAgentOptions:
    # Mirrors ClaudeOptionsBuilder.build's thinking resolution exactly (I-099
    # parity): `thinking` wins over deprecated `max_thinking_tokens`; only the
    # resolved config is set (the raw ClaudeAgentOptions.max_thinking_tokens
    # field is left at its default, same as the conversation path).
    thinking_config = _resolve_thinking(thinking, max_thinking_tokens)
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
        can_use_tool=cast(Any, can_use_tool),
        agents=cast(Any, agents),
        resume=resume,
        fork_session=fork_session,
        thinking=thinking_config,
        sandbox=cast(Any, sandbox),
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
    can_use_tool: Any | None = None,
    agents: dict[str, Any] | None = None,
    resume: str | None = None,
    fork_session: bool = False,
    thinking: dict[str, Any] | None = None,
    max_thinking_tokens: int | None = None,
    sandbox: dict[str, Any] | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream one shot query.

    Parity guarantee (I-099): ``thinking``, ``sandbox`` and
    ``max_thinking_tokens`` are forwarded into ``_build_options`` with the
    identical normalization ``ClaudeOptionsBuilder.build`` applies for the
    conversation path (``create_claude_conversation_adapter``), so a shared
    ``AgentConfig`` behaves the same on either claude_sdk dispatch path.
    """
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
        can_use_tool=can_use_tool,
        agents=agents,
        resume=resume,
        fork_session=fork_session,
        thinking=thinking,
        max_thinking_tokens=max_thinking_tokens,
        sandbox=sandbox,
    )

    # SDK constraint: a can_use_tool callback requires streaming input mode
    # (an AsyncIterable prompt) — a plain str prompt raises ValueError inside
    # claude_agent_sdk. Wrap the one-shot prompt into a single-message stream.
    prompt_arg: str | AsyncIterator[dict[str, Any]] = prompt
    if can_use_tool is not None:

        async def _streaming_prompt() -> AsyncIterator[dict[str, Any]]:
            yield {"type": "user", "message": {"role": "user", "content": prompt}}

        prompt_arg = _streaming_prompt()

    full_text = ""
    result_meta: dict[str, Any] = {}
    saw_partial_text = False
    saw_partial_thinking = False
    saw_result_message = False
    tool_names_by_id: dict[str, str] = {}

    async for message in _sdk_query(prompt=prompt_arg, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    if not saw_partial_text:
                        full_text += block.text
                        yield StreamEvent(type="text_delta", text=block.text)
                elif isinstance(block, ThinkingBlock):
                    if not saw_partial_thinking and block.thinking:
                        yield StreamEvent(type="thinking_delta", text=block.thinking)
                elif isinstance(block, ToolUseBlock):
                    correlation_id = (
                        getattr(block, "id", "")
                        or getattr(block, "tool_use_id", "")
                        or ""
                    )
                    if correlation_id:
                        tool_names_by_id[correlation_id] = block.name
                    yield StreamEvent(
                        type="tool_use_start",
                        tool_name=block.name,
                        tool_input=block.input,
                        correlation_id=correlation_id,
                    )
                elif isinstance(block, ToolResultBlock):
                    correlation_id = getattr(block, "tool_use_id", "") or ""
                    yield StreamEvent(
                        type="tool_use_result",
                        tool_name=tool_names_by_id.pop(correlation_id, ""),
                        tool_result=str(getattr(block, "content", "")),
                        correlation_id=correlation_id,
                        tool_error=bool(getattr(block, "is_error", False)),
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
            partial_thinking = _extract_partial_thinking_delta(message)
            if partial_thinking:
                saw_partial_thinking = True
                yield StreamEvent(type="thinking_delta", text=partial_thinking)

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
