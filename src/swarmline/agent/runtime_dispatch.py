"""Shared runtime dispatch helpers for Agent and Conversation."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, Callable, cast

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_factory_port import RuntimeFactoryPort, build_runtime_factory
from swarmline.runtime.types import Message

logger = logging.getLogger(__name__)


async def dispatch_runtime(
    runtime_name: str,
    claude_handler: Callable[[], AsyncIterator[Any]],
    portable_handler: Callable[[str], AsyncIterator[Any]],
) -> AsyncIterator[Any]:
    """Route execution to the requested runtime handler."""
    stream = (
        claude_handler()
        if runtime_name == "claude_sdk"
        else portable_handler(runtime_name)
    )
    async for event in stream:
        yield event


def build_tools_mcp_server(tools: tuple[Any, ...]) -> Any:
    """Create an in-process MCP server from a ToolDefinition tuple."""
    from swarmline.runtime.sdk_tools import create_mcp_server, mcp_tool

    sdk_tools = []
    for td in tools:
        adapted = _adapt_handler(td.handler)
        sdk_t = mcp_tool(td.name, td.description, td.parameters)(adapted)
        sdk_tools.append(sdk_t)

    return create_mcp_server("agent_tools", tools=sdk_tools)


def merge_hooks(config_hooks: Any, middleware: tuple[Any, ...]) -> Any:
    """Merge hooks from config and middleware.get_hooks()."""
    from swarmline.hooks.registry import HookRegistry

    registries: list[HookRegistry] = []

    if config_hooks:
        registries.append(config_hooks)

    for mw in middleware:
        hooks = mw.get_hooks()
        if hooks is not None:
            registries.append(hooks)

    if not registries:
        return None

    if len(registries) == 1:
        return registries[0]

    merged = HookRegistry()
    for reg in registries:
        for event_name in reg.list_events():
            for entry in reg.get_hooks(event_name):
                merged._add(event_name, entry.callback, entry.matcher)

    return merged


async def stream_claude_one_shot(
    prompt: str,
    config: AgentConfig,
    *,
    runtime_factory: RuntimeFactoryPort | None = None,
) -> AsyncIterator[Any]:
    """Execute a one-shot claude_sdk request with shared option wiring."""
    from swarmline.hooks.sdk_bridge import registry_to_sdk_hooks
    from swarmline.runtime.sdk_query import stream_one_shot_query
    from swarmline.runtime.adapter import StreamEvent

    factory = runtime_factory or build_runtime_factory()
    factory.validate_agent_config(config)

    mcp_servers = dict(config.mcp_servers)
    if config.tools:
        mcp_servers["__agent_tools__"] = build_tools_mcp_server(config.tools)

    merged_hooks = merge_hooks(config.hooks, config.middleware)
    sdk_hooks = registry_to_sdk_hooks(merged_hooks) if merged_hooks else None

    try:
        async for event in stream_one_shot_query(
            prompt,
            system_prompt=config.system_prompt,
            model=factory.resolve_agent_model(config),
            permission_mode=config.permission_mode,
            cwd=config.cwd,
            output_format=config.output_format,
            max_turns=config.max_turns,
            mcp_servers=mcp_servers if mcp_servers else None,
            hooks=sdk_hooks,
            max_budget_usd=config.max_budget_usd,
            fallback_model=config.fallback_model,
            betas=list(config.betas) if config.betas else None,
            env=dict(config.env) if config.env else None,
            setting_sources=(
                list(config.setting_sources) if config.setting_sources else None
            ),
            include_partial_messages=bool(
                config.native_config.get("include_partial_messages")
            ),
        ):
            yield event
    except Exception as exc:
        logger.exception("stream_claude_one_shot error")
        yield StreamEvent(type="error", text=str(exc))


async def create_claude_conversation_adapter(
    config: AgentConfig,
    *,
    runtime_factory: RuntimeFactoryPort | None = None,
) -> Any:
    """Create and connect a RuntimeAdapter for multi-turn claude_sdk use."""
    from swarmline.hooks.sdk_bridge import registry_to_sdk_hooks
    from swarmline.runtime.adapter import RuntimeAdapter
    from swarmline.runtime.options_builder import ClaudeOptionsBuilder

    factory = runtime_factory or build_runtime_factory()
    factory.validate_agent_config(config)

    merged_hooks = merge_hooks(config.hooks, config.middleware)
    builder = ClaudeOptionsBuilder(
        cwd=config.cwd,
        override_model=factory.resolve_agent_model(config),
    )

    sdk_mcp_servers: dict[str, Any] = {}
    if config.tools:
        sdk_mcp_servers["__agent_tools__"] = build_tools_mcp_server(config.tools)

    sdk_hooks = registry_to_sdk_hooks(merged_hooks) if merged_hooks else None

    opts = builder.build(
        role_id="agent",
        system_prompt=config.system_prompt,
        mcp_servers=config.mcp_servers or None,
        sdk_mcp_servers=sdk_mcp_servers if sdk_mcp_servers else None,
        hooks=sdk_hooks,
        output_format=config.output_format,
        continue_conversation=True,
        max_turns=config.max_turns,
        permission_mode=cast(Any, config.permission_mode),
        setting_sources=cast(
            Any,
            list(config.setting_sources) if config.setting_sources else None,
        ),
        betas=cast(Any, list(config.betas) if config.betas else None),
        max_budget_usd=config.max_budget_usd,
        thinking=config.thinking,
        max_thinking_tokens=config.max_thinking_tokens,
        fallback_model=config.fallback_model,
        sandbox=cast(Any, config.sandbox),
        env=dict(config.env) if config.env else None,
        include_partial_messages=bool(config.native_config.get("include_partial_messages")),
    )

    adapter = RuntimeAdapter(opts)
    await adapter.connect()
    return adapter


async def run_portable_runtime(
    agent_config: AgentConfig,
    runtime_name: str,
    *,
    messages: list[Message],
    system_prompt: str,
    runtime_factory: RuntimeFactoryPort | None = None,
    session_id: str | None = None,
    event_adapter: Callable[[Any], Any],
    error_factory: Callable[[Exception], Any],
    logger: logging.Logger,
    error_context: str,
) -> AsyncIterator[Any]:
    """Create, run, adapt, and cleanup a portable runtime invocation."""
    from swarmline.agent.runtime_wiring import build_portable_runtime_plan

    runtime_plan = build_portable_runtime_plan(
        agent_config,
        runtime_name,
        session_id=session_id,
        runtime_factory=runtime_factory,
    )
    factory = runtime_factory or build_runtime_factory()
    runtime = factory.create(
        config=runtime_plan.config,
        **runtime_plan.create_kwargs,
    )

    try:
        async for event in runtime.run(
            messages=messages,
            system_prompt=system_prompt,
            active_tools=runtime_plan.active_tools,
        ):
            yield event_adapter(event)
    except Exception as exc:
        logger.exception("%s error", error_context)
        yield error_factory(exc)
    finally:
        await runtime.cleanup()


def _adapt_handler(handler: Any) -> Any:
    """Adapt a user handler to the SDK MCP handler contract."""
    async def adapted(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await handler(**args)
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "is_error": True,
            }

        if isinstance(result, dict) and "content" in result:
            return result

        return {
            "content": [{"type": "text", "text": str(result)}],
        }

    return adapted


class RuntimeEventAdapter:
    """Adapter from RuntimeEvent to a StreamEvent-like interface."""

    def __init__(self, event: Any) -> None:
        self._event = event
        etype = event.type
        data = event.data or {}

        if etype == "thinking_delta":
            self.type = "thinking_delta"
            self.text = data.get("text", "")
        elif etype == "assistant_delta":
            self.type = "text_delta"
            self.text = data.get("text", "")
        elif etype == "final":
            self.type = "done"
            self.text = data.get("text", "")
            self.is_final = True
            self.new_messages = data.get("new_messages", [])
        elif etype == "error":
            self.type = "error"
            self.text = data.get("message", "Unknown error")
        elif etype == "tool_call_started":
            self.type = "tool_use_start"
            self.text = ""
            self.tool_name = data.get("name", "")
            self.tool_input = data.get("args")
            self.correlation_id = data.get("correlation_id", "")
        elif etype == "tool_call_finished":
            self.type = "tool_use_result"
            self.text = ""
            self.tool_name = data.get("name", "")
            self.tool_result = data.get("result_summary", "")
            self.correlation_id = data.get("correlation_id", "")
            self.tool_error = not data.get("ok", True)
        elif etype == "approval_required":
            self.type = "approval_required"
            self.text = data.get("description") or data.get("action_name", "")
            self.tool_name = data.get("action_name", "")
            self.tool_input = data.get("args")
            self.allowed_decisions = data.get("allowed_decisions")
            self.interrupt_id = data.get("interrupt_id")
        elif etype == "user_input_requested":
            self.type = "user_input_requested"
            self.text = data.get("prompt", "")
            self.interrupt_id = data.get("interrupt_id")
        elif etype == "native_notice":
            self.type = "native_notice"
            self.text = data.get("text", "")
        else:
            self.type = etype
            self.text = data.get("text", "")

        if not hasattr(self, "is_final"):
            self.is_final = False
        if not hasattr(self, "tool_name"):
            self.tool_name = ""
        if not hasattr(self, "tool_input"):
            self.tool_input = None
        if not hasattr(self, "tool_result"):
            self.tool_result = ""
        if not hasattr(self, "correlation_id"):
            self.correlation_id = ""
        if not hasattr(self, "tool_error"):
            self.tool_error = False
        if not hasattr(self, "allowed_decisions"):
            self.allowed_decisions = None
        if not hasattr(self, "interrupt_id"):
            self.interrupt_id = None
        if not hasattr(self, "new_messages"):
            self.new_messages = []

        self.session_id = data.get("session_id")
        self.total_cost_usd = data.get("total_cost_usd")
        self.usage = data.get("usage")
        self.structured_output = data.get("structured_output")
        self.native_metadata = data.get("native_metadata") or data.get("metadata")


class ErrorEvent:
    """Simple error event."""

    def __init__(self, message: str) -> None:
        self.type = "error"
        self.text = message
        self.is_final = False
        self.session_id = None
        self.total_cost_usd = None
        self.usage = None
        self.structured_output = None
        self.native_metadata = None
        self.tool_name = ""
        self.tool_input = None
        self.tool_result = ""
        self.allowed_decisions = None
        self.interrupt_id = None
        self.new_messages: list[Any] = []
