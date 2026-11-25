"""Shared runtime dispatch helpers for Agent and Conversation."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, Callable, cast

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_factory_port import (
    RuntimeFactoryPort,
    build_runtime_factory,
)
from swarmline.observability.redaction import redact_secrets
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


def _effective_setting_sources(config: AgentConfig) -> list[str] | None:
    """setting_sources for claude_sdk, honoring the unified
    ``project_instructions`` switch: explicit setting_sources win; otherwise
    ``project_instructions=True`` maps to the native ["project"] source."""
    if config.setting_sources:
        return list(config.setting_sources)
    if getattr(config, "project_instructions", False):
        return ["project"]
    return None


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


def _tool_policy_to_sdk_callback(policy: Any, config: AgentConfig) -> Any:
    """Adapt a swarmline ToolPolicy into a claude-agent-sdk CanUseTool callback.

    The returned async callback maps ``PermissionAllow``/``PermissionDeny``
    decisions onto the SDK's ``PermissionResultAllow``/``PermissionResultDeny``.
    """
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

    from swarmline.policy.tool_policy import PermissionDeny, ToolPolicyInput

    active_skill_ids = list(config.mcp_servers.keys())
    allowed_local_tools: set[str] = set()
    if config.tools:
        # Agent tools are exposed via the in-process "__agent_tools__" MCP server.
        active_skill_ids.append("__agent_tools__")
        for td in config.tools:
            allowed_local_tools.add(td.name)
            allowed_local_tools.add(f"mcp____agent_tools____{td.name}")

    async def _can_use_tool(
        tool_name: str,
        input_data: dict[str, Any],
        context: Any,
    ) -> Any:
        _ = context
        state = ToolPolicyInput(
            tool_name=tool_name,
            input_data=input_data,
            active_skill_ids=active_skill_ids,
            allowed_local_tools=allowed_local_tools,
        )
        decision = policy.can_use_tool(tool_name, input_data, state)
        if isinstance(decision, PermissionDeny):
            return PermissionResultDeny(behavior="deny", message=decision.message)
        return PermissionResultAllow(
            behavior="allow",
            updated_input=decision.updated_input,
        )

    return _can_use_tool


def _resolve_claude_can_use_tool(config: AgentConfig) -> Any | None:
    """Resolve the effective SDK can_use_tool callback for claude_sdk paths.

    Priority: explicit ``config.can_use_tool`` > adapter derived from
    ``config.tool_policy``. An explicit callback combined with
    permission_mode="bypassPermissions" is a hard error (the SDK never consults
    the callback in that mode); a tool_policy in that mode is skipped with a
    warning to preserve backward compatibility with portable-runtime configs.
    """
    if config.can_use_tool is not None:
        if config.permission_mode == "bypassPermissions":
            raise ValueError(
                "AgentConfig.can_use_tool requires a permission mode that "
                'consults the callback, but permission_mode="bypassPermissions" '
                "bypasses all permission checks so the callback would never "
                'run. Set AgentConfig(permission_mode="default").'
            )
        return config.can_use_tool

    if config.tool_policy is None:
        return None

    if config.permission_mode == "bypassPermissions":
        logger.warning(
            "AgentConfig.tool_policy is set but permission_mode="
            '"bypassPermissions"; the claude_sdk runtime cannot enforce the '
            'policy natively. Set permission_mode="default" to enable native '
            "enforcement."
        )
        return None

    return _tool_policy_to_sdk_callback(config.tool_policy, config)


async def stream_claude_one_shot(
    prompt: str,
    config: AgentConfig,
    *,
    runtime_factory: RuntimeFactoryPort | None = None,
) -> AsyncIterator[Any]:
    """Execute a one-shot claude_sdk request with shared option wiring.

    Parity guarantee (I-099): every kwarg forwarded to
    ``stream_one_shot_query`` here mirrors what
    ``create_claude_conversation_adapter`` forwards to
    ``ClaudeOptionsBuilder.build`` for the same ``AgentConfig`` fields —
    including ``thinking``/``sandbox``/``max_thinking_tokens`` and the
    ``output_type``-derived ``output_format`` (via ``_effective_output_format``,
    the same helper the pi_sdk/cli dispatch-structured-output path uses) — so
    ``Agent.query()``/``Agent.stream()`` behave like ``Agent.conversation()``.
    """
    from swarmline.hooks.sdk_bridge import registry_to_sdk_hooks
    from swarmline.runtime.sdk_query import stream_one_shot_query
    from swarmline.runtime.adapter import StreamEvent

    factory = runtime_factory or build_runtime_factory()
    factory.validate_agent_config(config)

    can_use_tool = _resolve_claude_can_use_tool(config)

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
            output_format=_effective_output_format(config),
            max_turns=config.max_turns,
            mcp_servers=mcp_servers if mcp_servers else None,
            hooks=sdk_hooks,
            max_budget_usd=config.max_budget_usd,
            fallback_model=config.fallback_model,
            betas=list(config.betas) if config.betas else None,
            env=dict(config.env) if config.env else None,
            setting_sources=_effective_setting_sources(config),
            include_partial_messages=bool(
                config.native_config.get("include_partial_messages")
            ),
            can_use_tool=can_use_tool,
            agents=dict(config.native_agents) if config.native_agents else None,
            resume=config.resume_session_id,
            fork_session=config.fork_session,
            # AgentConfig.__post_init__ normalises ThinkingConfig dataclass →
            # dict, so by the time we read this it's always dict[str, Any] |
            # None (same invariant create_claude_conversation_adapter relies
            # on for the conversation path — see the comment there).
            thinking=cast("dict[str, Any] | None", config.thinking),
            max_thinking_tokens=config.max_thinking_tokens,
            sandbox=cast(Any, config.sandbox),
        ):
            yield event
    except Exception as exc:
        redacted = redact_secrets(str(exc))
        logger.error(
            "stream_claude_one_shot error exc_type=%s error=%s",
            type(exc).__name__,
            redacted,
        )
        yield StreamEvent(
            type="error",
            text=f"Claude SDK error ({type(exc).__name__}): {redacted}",
        )


async def create_claude_conversation_adapter(
    config: AgentConfig,
    *,
    runtime_factory: RuntimeFactoryPort | None = None,
) -> Any:
    """Create and connect a RuntimeAdapter for multi-turn claude_sdk use.

    Parity guarantee (I-099): ``output_format`` is derived via
    ``_effective_output_format`` — the same helper ``stream_claude_one_shot``
    uses — so an ``output_type``-only ``AgentConfig`` produces the identical
    schema on ``Agent.conversation()`` as on ``Agent.query()``/``.stream()``;
    an explicit ``output_format`` still wins over ``output_type`` on both.
    """
    from swarmline.hooks.sdk_bridge import registry_to_sdk_hooks
    from swarmline.runtime.adapter import RuntimeAdapter
    from swarmline.runtime.options_builder import ClaudeOptionsBuilder

    factory = runtime_factory or build_runtime_factory()
    factory.validate_agent_config(config)

    can_use_tool = _resolve_claude_can_use_tool(config)

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
        output_format=_effective_output_format(config),
        # Resume-by-id and continue-latest are mutually exclusive: when a
        # session id is given, resume that session instead of forcing
        # continue_conversation.
        continue_conversation=config.resume_session_id is None,
        resume=config.resume_session_id,
        fork_session=config.fork_session,
        can_use_tool=can_use_tool,
        agents=cast(Any, config.native_agents),
        max_turns=config.max_turns,
        permission_mode=cast(Any, config.permission_mode),
        setting_sources=cast(Any, _effective_setting_sources(config)),
        betas=cast(Any, list(config.betas) if config.betas else None),
        max_budget_usd=config.max_budget_usd,
        # AgentConfig.__post_init__ normalises ThinkingConfig dataclass → dict,
        # so by the time we read this it's always dict[str, Any] | None.
        thinking=cast("dict[str, Any] | None", config.thinking),
        max_thinking_tokens=config.max_thinking_tokens,
        fallback_model=config.fallback_model,
        sandbox=cast(Any, config.sandbox),
        env=dict(config.env) if config.env else None,
        include_partial_messages=bool(
            config.native_config.get("include_partial_messages")
        ),
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

    messages, system_prompt = await _apply_project_instructions(
        agent_config, runtime_name, messages, system_prompt, factory
    )

    emulate_structured = _needs_dispatch_structured_output(agent_config, runtime_name)
    if emulate_structured:
        from swarmline.runtime.structured_output import (
            append_structured_output_instruction,
        )

        system_prompt = append_structured_output_instruction(
            system_prompt, _effective_output_format(agent_config)
        )

    try:
        async for event in runtime.run(
            messages=messages,
            system_prompt=system_prompt,
            active_tools=runtime_plan.active_tools,
        ):
            if emulate_structured and getattr(event, "type", "") == "final":
                _attach_structured_output(agent_config, event)
            yield event_adapter(event)
    except Exception as exc:
        logger.exception("%s error", error_context)
        yield error_factory(exc)
    finally:
        await runtime.cleanup()


#: Runtimes whose structured output is emulated at the dispatch layer.
#: thin/deepagents/openai_agents implement structured output inside the
#: runtime (native or prompt-based); pi_sdk and cli have no in-runtime
#: mechanism, so the dispatch layer injects the schema instruction and
#: parses/validates the final text (plan D1).
_DISPATCH_STRUCTURED_RUNTIMES = frozenset({"pi_sdk", "cli"})


def _effective_output_format(config: AgentConfig) -> dict[str, Any] | None:
    if config.output_format is not None:
        return config.output_format
    if config.output_type is not None:
        from swarmline.runtime.structured_output import extract_pydantic_schema

        return extract_pydantic_schema(cast(Any, config.output_type))
    return None


def _needs_dispatch_structured_output(config: AgentConfig, runtime_name: str) -> bool:
    if runtime_name not in _DISPATCH_STRUCTURED_RUNTIMES:
        return False
    return config.output_format is not None or config.output_type is not None


def _attach_structured_output(config: AgentConfig, event: Any) -> None:
    """Parse/validate structured output from the final text (best effort)."""
    from swarmline.runtime.structured_output import try_resolve_structured_output

    data = getattr(event, "data", None)
    if not isinstance(data, dict) or data.get("structured_output") is not None:
        return
    text = data.get("text") or ""
    if not text:
        return
    parsed, error = try_resolve_structured_output(
        text, config.output_format, config.output_type
    )
    if parsed is not None:
        data["structured_output"] = parsed
    elif error:
        logger.warning("dispatch structured output validation failed: %s", error)


async def _apply_project_instructions(
    agent_config: AgentConfig,
    runtime_name: str,
    messages: list[Message],
    system_prompt: str,
    factory: RuntimeFactoryPort,
) -> tuple[list[Message], str]:
    """Uniform project-instruction loading for portable runtimes (plan D3).

    When ``AgentConfig.project_instructions`` is on and the runtime's
    capability level is ``emulated``, discovered AGENTS.md/RULES.md/
    CLAUDE.md/GEMINI.md content is prepended to the system prompt. Runtimes
    with ``native`` support (claude_sdk setting_sources, pi_sdk resource
    loader) load instructions themselves and are left untouched.
    """
    if not getattr(agent_config, "project_instructions", False):
        return messages, system_prompt

    try:
        caps = factory.get_capabilities(runtime_override=runtime_name)
        level = caps.resolve(agent_config).level("project_instructions")
    except Exception:  # custom runtimes without v2 capabilities
        level = "emulated"

    if level != "emulated":
        return messages, system_prompt

    from swarmline.project_instruction_filter import ProjectInstructionFilter

    instruction_filter = ProjectInstructionFilter(cwd=agent_config.cwd)
    return await instruction_filter.filter(messages, system_prompt)


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
