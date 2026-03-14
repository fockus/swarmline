"""Agent — high-level executor для cognitia."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from cognitia.agent.config import AgentConfig
from cognitia.agent.result import Result

logger = logging.getLogger(__name__)


class Agent:
    """High-level facade для взаимодействия с AI-агентом.

    Поддерживает:
    - query(prompt) → Result (one-shot)
    - stream(prompt) → AsyncIterator[StreamEvent] (streaming)
    - conversation() → Conversation (multi-turn)
    """

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._runtime: Any = None

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def runtime_capabilities(self) -> Any:
        """Capability descriptor выбранного runtime для app-level introspection."""
        from cognitia.runtime.factory import RuntimeFactory

        factory = RuntimeFactory()
        return factory.get_capabilities(self._build_runtime_config(self._config.runtime))

    async def query(self, prompt: str) -> Result:
        """One-shot запрос → Result.

        1. Apply middleware.before_query chain
        2. Execute stream
        3. Collect result from done event
        4. Apply middleware.after_result chain
        """
        # 1. Middleware before_query
        effective_prompt = await apply_before_query(
            prompt, self._config.middleware, self._config,
        )

        # 2. Execute + collect
        collected = await collect_stream_result(self._execute_stream(effective_prompt))

        # 3. Build Result
        result = Result(**collected)

        # 4. Middleware after_result
        for mw in self._config.middleware:
            result = await mw.after_result(result)

        return result

    async def stream(self, prompt: str) -> AsyncIterator[Any]:
        """Streaming запрос → AsyncIterator[StreamEvent].

        Middleware before_query применяется, after_result — нет (streaming).
        """
        effective_prompt = await apply_before_query(
            prompt, self._config.middleware, self._config,
        )

        async for event in self._execute_stream(effective_prompt):
            yield event

    def conversation(self, session_id: str | None = None) -> Any:
        """Создать multi-turn Conversation."""
        from cognitia.agent.conversation import Conversation

        return Conversation(agent=self, session_id=session_id)

    async def cleanup(self) -> None:
        """Освободить ресурсы (runtime, adapter, subprocess)."""
        if self._runtime is not None:
            if hasattr(self._runtime, "cleanup"):
                await self._runtime.cleanup()
            self._runtime = None

    async def __aenter__(self) -> Agent:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.cleanup()

    # -----------------------------------------------------------------------
    # Internal: runtime dispatch
    # -----------------------------------------------------------------------

    async def _execute_stream(self, prompt: str) -> AsyncIterator[Any]:
        """Выполнить prompt через выбранный runtime.

        Routing:
        - claude_sdk → RuntimeAdapter + ClaudeOptionsBuilder (warm subprocess)
        - thin/deepagents → RuntimeFactory → AgentRuntime.run()
        """
        runtime_name = self._config.runtime

        if runtime_name == "claude_sdk":
            async for event in self._execute_claude_sdk(prompt):
                yield event
        else:
            async for event in self._execute_agent_runtime(prompt, runtime_name):
                yield event

    async def _execute_claude_sdk(self, prompt: str) -> AsyncIterator[Any]:
        """Execute через Claude Agent SDK (one-shot streaming query)."""
        from cognitia.hooks.sdk_bridge import registry_to_sdk_hooks
        from cognitia.runtime.sdk_query import stream_one_shot_query

        # Собираем MCP серверы из tools
        mcp_servers = dict(self._config.mcp_servers)
        if self._config.tools:
            sdk_server = self._build_tools_mcp_server()
            mcp_servers["__agent_tools__"] = sdk_server

        merged_hooks = merge_hooks(self._config.hooks, self._config.middleware)
        sdk_hooks = registry_to_sdk_hooks(merged_hooks) if merged_hooks else None

        try:
            async for event in stream_one_shot_query(
                prompt,
                system_prompt=self._config.system_prompt,
                model=self._config.resolved_model,
                permission_mode=self._config.permission_mode,
                cwd=self._config.cwd,
                output_format=self._config.output_format,
                max_turns=self._config.max_turns,
                mcp_servers=mcp_servers if mcp_servers else None,
                hooks=sdk_hooks,
                max_budget_usd=self._config.max_budget_usd,
                fallback_model=self._config.fallback_model,
                betas=list(self._config.betas) if self._config.betas else None,
                env=dict(self._config.env) if self._config.env else None,
                setting_sources=(
                    list(self._config.setting_sources)
                    if self._config.setting_sources
                    else None
                ),
                include_partial_messages=bool(
                    self._config.native_config.get("include_partial_messages")
                ),
            ):
                yield event
        except Exception as exc:
            from cognitia.runtime.adapter import StreamEvent

            logger.exception("Agent._execute_claude_sdk error")
            yield StreamEvent(type="error", text=str(exc))

    async def _execute_agent_runtime(
        self, prompt: str, runtime_name: str
    ) -> AsyncIterator[Any]:
        """Execute через AgentRuntime (thin/deepagents)."""
        from cognitia.runtime.factory import RuntimeFactory
        from cognitia.runtime.types import Message

        config = self._build_runtime_config(runtime_name)
        factory = RuntimeFactory()
        runtime = factory.create(
            config=config,
            tool_executors={td.name: td.handler for td in self._config.tools},
        )

        messages = [Message(role="user", content=prompt)]
        active_tools = [td.to_tool_spec() for td in self._config.tools]

        try:
            async for event in runtime.run(
                messages=messages,
                system_prompt=self._config.system_prompt,
                active_tools=active_tools,
            ):
                # Конвертируем RuntimeEvent → StreamEvent-like
                yield _RuntimeEventAdapter(event)
        except Exception as exc:
            logger.exception("Agent._execute_agent_runtime error")
            yield _ErrorEvent(str(exc))
        finally:
            await runtime.cleanup()

    def _build_tools_mcp_server(self) -> Any:
        """Создать in-process MCP server из @tool definitions."""
        return build_tools_mcp_server(self._config.tools)

    def _build_runtime_config(self, runtime_name: str) -> Any:
        """Собрать RuntimeConfig из AgentConfig для portable/native runtime path."""
        from cognitia.runtime.types import RuntimeConfig

        return RuntimeConfig(
            runtime_name=runtime_name,
            model=self._config.resolved_model,
            output_format=self._config.output_format,
            feature_mode=self._config.feature_mode,
            required_capabilities=self._config.require_capabilities,
            allow_native_features=self._config.allow_native_features,
            native_config=dict(self._config.native_config),
        )

    def _merge_hooks(self) -> Any:
        """Merge hooks из config.hooks + middleware.get_hooks()."""
        return merge_hooks(self._config.hooks, self._config.middleware)


def build_tools_mcp_server(tools: tuple[Any, ...]) -> Any:
    """Создать in-process MCP server из ToolDefinition tuple."""
    from cognitia.runtime.sdk_tools import create_mcp_server, mcp_tool

    sdk_tools = []
    for td in tools:
        adapted = _adapt_handler(td.handler)
        sdk_t = mcp_tool(td.name, td.description, td.parameters)(adapted)
        sdk_tools.append(sdk_t)

    return create_mcp_server("agent_tools", tools=sdk_tools)


def merge_hooks(config_hooks: Any, middleware: tuple[Any, ...]) -> Any:
    """Merge hooks из config и middleware.get_hooks()."""
    from cognitia.hooks.registry import HookRegistry

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


def _adapt_handler(handler: Any) -> Any:
    """Адаптировать user handler → SDK MCP handler contract.

    SDK ожидает: handler(args_dict) -> {"content": [{"type": "text", "text": "..."}]}
    User handler: handler(a=1, b=2) -> "result" или любой тип.
    """

    async def adapted(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await handler(**args)
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "is_error": True,
            }

        # Если handler уже вернул MCP-формат — passthrough
        if isinstance(result, dict) and "content" in result:
            return result

        # Оборачиваем в MCP-формат
        return {
            "content": [{"type": "text", "text": str(result)}],
        }

    return adapted


async def apply_before_query(
    prompt: str, middleware: tuple[Any, ...], config: Any,
) -> str:
    """Применить middleware.before_query chain к prompt."""
    for mw in middleware:
        prompt = await mw.before_query(prompt, config)
    return prompt


async def collect_stream_result(stream: AsyncIterator[Any]) -> dict[str, Any]:
    """Собрать Result-поля из потока StreamEvent-like объектов.

    Используется в Agent.query() и Conversation.say() для единообразного
    сбора text/session_id/cost/usage/structured_output/error из потока.
    """
    text = ""
    session_id = None
    total_cost_usd = None
    usage = None
    structured_output = None
    native_metadata = None
    error = None

    async for event in stream:
        etype = event.type
        if etype == "text_delta":
            text += event.text
        elif etype == "done":
            text = event.text or text
            session_id = getattr(event, "session_id", None)
            total_cost_usd = getattr(event, "total_cost_usd", None)
            usage = getattr(event, "usage", None)
            structured_output = getattr(event, "structured_output", None)
            native_metadata = getattr(event, "native_metadata", None)
        elif etype == "error":
            error = event.text or "Unknown error"

    return {
        "text": text,
        "session_id": session_id,
        "total_cost_usd": total_cost_usd,
        "usage": usage,
        "structured_output": structured_output,
        "native_metadata": native_metadata,
        "error": error,
    }


class _RuntimeEventAdapter:
    """Адаптер RuntimeEvent → StreamEvent-like interface."""

    def __init__(self, event: Any) -> None:
        self._event = event
        etype = event.type
        data = event.data or {}

        # Маппинг RuntimeEvent → StreamEvent types
        if etype == "assistant_delta":
            self.type = "text_delta"
            self.text = data.get("text", "")
        elif etype == "final":
            self.type = "done"
            self.text = data.get("text", "")
            self.is_final = True
        elif etype == "error":
            self.type = "error"
            self.text = data.get("message", "Unknown error")
        elif etype == "tool_call_started":
            self.type = "tool_use_start"
            self.text = ""
            self.tool_name = data.get("name", "")
            self.tool_input = data.get("args")
        elif etype == "tool_call_finished":
            self.type = "tool_use_result"
            self.text = ""
            self.tool_result = data.get("result_summary", "")
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

        # Defaults for attributes that may not be set
        if not hasattr(self, "is_final"):
            self.is_final = False
        if not hasattr(self, "tool_name"):
            self.tool_name = ""
        if not hasattr(self, "tool_input"):
            self.tool_input = None
        if not hasattr(self, "tool_result"):
            self.tool_result = ""
        if not hasattr(self, "allowed_decisions"):
            self.allowed_decisions = None
        if not hasattr(self, "interrupt_id"):
            self.interrupt_id = None

        self.session_id = data.get("session_id")
        self.total_cost_usd = data.get("total_cost_usd")
        self.usage = data.get("usage")
        self.structured_output = data.get("structured_output")
        self.native_metadata = data.get("native_metadata") or data.get("metadata")


class _ErrorEvent:
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
