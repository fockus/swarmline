"""Agent - high-level executor for swarmline."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any, TypeVar

from swarmline.agent.config import AgentConfig
from swarmline.agent.result import Result
from swarmline.agent.runtime_factory_port import RuntimeFactoryPort, build_runtime_factory
from swarmline.agent.runtime_dispatch import (
    dispatch_runtime,
    merge_hooks,
    run_portable_runtime,
    stream_claude_one_shot,
)
from swarmline.runtime.types import Message

T = TypeVar("T")

logger = logging.getLogger(__name__)


class Agent:
    """High-level facade for interacting with the AI agent.

    Supports:
    - query(prompt) → Result (one-shot)
    - stream(prompt) → AsyncIterator[StreamEvent] (streaming)
    - conversation() → Conversation (multi-turn)
    """

    def __init__(
        self,
        config: AgentConfig,
        runtime_factory: RuntimeFactoryPort | None = None,
    ) -> None:
        self._runtime_factory = runtime_factory
        self.runtime_factory.validate_agent_config(config)
        self._config = config
        self._runtime: Any = None

    @property
    def runtime_factory(self) -> RuntimeFactoryPort:
        """Application-facing runtime factory seam."""
        return self._runtime_factory or build_runtime_factory()

    @property
    def config(self) -> AgentConfig:
        return self._config

    @property
    def runtime_capabilities(self) -> Any:
        """Capability descriptor for the selected runtime for app-level introspection."""
        factory = self.runtime_factory
        config = self._build_runtime_config(self._config.runtime, runtime_factory=factory)
        return factory.get_capabilities(config)

    async def query(
        self,
        prompt: str,
        *,
        messages: list[Message] | None = None,
    ) -> Result:
        """One-shot request -> Result.

        Parameters
        ----------
        prompt:
            The user prompt (appended as the final user message).
        messages:
            Optional conversation history to prepend before the current prompt.
            Each message is a ``Message(role, content, ...)``.
            If None or empty, behaves as a standalone one-shot query.
        """
        return await self._query_with_config(prompt, self._config, messages=messages)

    async def _query_with_config(
        self,
        prompt: str,
        config: AgentConfig,
        *,
        messages: list[Message] | None = None,
    ) -> Result:
        """One-shot request -> Result.

        1. Apply middleware.before_query chain
        2. Execute stream
        3. Collect result from done event
        4. Apply middleware.after_result chain
        """
        # 1. Middleware before_query
        effective_prompt = await apply_before_query(
            prompt,
            config.middleware,
            config,
        )

        # 2. Execute + collect
        stream = (
            self._execute_stream(effective_prompt, messages=messages)
            if config is self._config
            else self._execute_stream(effective_prompt, config, messages=messages)
        )
        collected = await collect_stream_result(stream)
        result_payload = dict(collected)
        new_messages = result_payload.pop("new_messages", None)

        # 3. Build Result
        result = Result(**result_payload)

        # 4. Middleware after_result
        for mw in config.middleware:
            result = await mw.after_result(result)

        if new_messages is not None:
            object.__setattr__(result, "new_messages", new_messages)

        return result

    async def query_structured(
        self,
        prompt: str,
        output_type: type[T],
        *,
        max_retries: int | None = None,
        structured_mode: Any | None = None,
    ) -> T:
        """One-shot request returning a validated Pydantic model.

        Creates a temporary AgentConfig with output_type set,
        runs query(), and returns the validated structured_output.

        Parameters
        ----------
        prompt:
            The user prompt.
        output_type:
            A Pydantic BaseModel subclass. The LLM response is parsed
            and validated against this type. Retry on validation error.
        max_retries:
            Override max_model_retries for structured output validation.
            Default: uses the runtime's default (2).

        Returns
        -------
        T
            A validated instance of ``output_type``.

        Raises
        ------
        StructuredOutputError
            If all retries are exhausted and validation still fails.
        """
        from swarmline.agent.structured import StructuredOutputError

        # Build a temporary config with output_type set
        overrides: dict[str, Any] = {"output_type": output_type}
        if max_retries is not None:
            overrides["max_model_retries"] = max_retries
        if structured_mode is not None:
            overrides["structured_mode"] = structured_mode
        if self._config.output_format is None:
            schema_builder = getattr(output_type, "model_json_schema", None)
            if callable(schema_builder):
                overrides["output_format"] = schema_builder()
        config = replace(self._config, **overrides)

        result = await self._query_with_config(prompt, config)

        if result.structured_output is not None:
            return result.structured_output  # type: ignore[return-value]

        raise StructuredOutputError(
            f"Failed to parse structured output as {output_type.__name__}. "
            f"Raw text: {result.text[:200]}"
        )

    async def stream(self, prompt: str) -> AsyncIterator[Any]:
        async for event in self._stream_with_config(prompt, self._config):
            yield event

    async def _stream_with_config(self, prompt: str, config: AgentConfig) -> AsyncIterator[Any]:
        """Streaming request -> AsyncIterator[StreamEvent].

        Middleware before_query applies, after_result does not (streaming).
        """
        effective_prompt = await apply_before_query(
            prompt,
            config.middleware,
            config,
        )

        stream = (
            self._execute_stream(effective_prompt)
            if config is self._config
            else self._execute_stream(effective_prompt, config)
        )
        async for event in stream:
            yield event

    def conversation(self, session_id: str | None = None) -> Any:
        """Create a multi-turn Conversation."""
        from swarmline.agent.conversation import Conversation

        return Conversation(agent=self, session_id=session_id)

    async def cleanup(self) -> None:
        """Release resources (runtime, adapter, subprocess)."""
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

    async def _execute_stream(
        self,
        prompt: str,
        config: AgentConfig | None = None,
        *,
        messages: list[Message] | None = None,
    ) -> AsyncIterator[Any]:
        """Execute the prompt via the selected runtime.

        Routing:
        - claude_sdk → RuntimeAdapter + ClaudeOptionsBuilder (warm subprocess)
        - thin/deepagents → RuntimeFactory → AgentRuntime.run()
        """
        effective_config = config or self._config
        async for event in dispatch_runtime(
            effective_config.runtime,
            lambda: self._execute_claude_sdk(prompt, effective_config, messages=messages),
            lambda runtime_name: self._execute_agent_runtime(
                prompt,
                runtime_name,
                effective_config,
                messages=messages,
            ),
        ):
            yield event

    async def _execute_claude_sdk(
        self,
        prompt: str,
        config: AgentConfig | None = None,
        *,
        messages: list[Message] | None = None,
    ) -> AsyncIterator[Any]:
        """Execute via Claude Agent SDK (one-shot streaming query)."""
        effective_config = config or self._config
        effective_prompt = prompt
        if messages:
            history_text = "\n".join(
                f"[{m.role}]: {m.content}" for m in messages
            )
            effective_prompt = f"[Conversation history]\n{history_text}\n\n[Current message]\n{prompt}"
        async for event in stream_claude_one_shot(
            effective_prompt,
            effective_config,
            runtime_factory=self.runtime_factory,
        ):
            yield event

    async def _execute_agent_runtime(
        self,
        prompt: str,
        runtime_name: str,
        config: AgentConfig | None = None,
        *,
        messages: list[Message] | None = None,
    ) -> AsyncIterator[Any]:
        """Execute via AgentRuntime (thin/deepagents)."""
        from swarmline.runtime.types import Message as RuntimeMessage

        effective_config = config or self._config
        api_messages: list[RuntimeMessage] = []
        if messages:
            api_messages.extend(
                RuntimeMessage(role=m.role, content=m.content) for m in messages
            )
        api_messages.append(RuntimeMessage(role="user", content=prompt))
        async for event in run_portable_runtime(
            agent_config=effective_config,
            runtime_name=runtime_name,
            messages=api_messages,
            system_prompt=effective_config.system_prompt,
            runtime_factory=self.runtime_factory,
            event_adapter=_RuntimeEventAdapter,
            error_factory=lambda exc: _ErrorEvent(str(exc)),
            logger=logger,
            error_context="Agent._execute_agent_runtime",
        ):
            yield event

    def _build_tools_mcp_server(self, config: AgentConfig | None = None) -> Any:
        """Create an in-process MCP server from @tool definitions."""
        effective_config = config or self._config
        return build_tools_mcp_server(effective_config.tools)

    def _build_runtime_config(
        self,
        runtime_name: str,
        config: AgentConfig | None = None,
        *,
        runtime_factory: RuntimeFactoryPort | None = None,
    ) -> Any:
        """Build RuntimeConfig from AgentConfig for the portable/native runtime path."""
        from swarmline.runtime.types import RuntimeConfig

        effective_config = config or self._config
        factory = runtime_factory or self.runtime_factory
        factory.validate_agent_config(effective_config)

        return RuntimeConfig(
            runtime_name=runtime_name,
            max_model_retries=(
                effective_config.max_model_retries
                if effective_config.max_model_retries is not None
                else RuntimeConfig().max_model_retries
            ),
            model=factory.resolve_agent_model(effective_config),
            output_format=effective_config.output_format,
            output_type=effective_config.output_type,
            structured_mode=effective_config.structured_mode,
            structured_schema_name=effective_config.structured_schema_name,
            structured_strict=effective_config.structured_strict,
            request_options=effective_config.request_options,
            feature_mode=effective_config.feature_mode,
            required_capabilities=effective_config.require_capabilities,
            allow_native_features=effective_config.allow_native_features,
            native_config=dict(effective_config.native_config),
        )

    def _merge_hooks(self) -> Any:
        """Merge hooks from config.hooks + middleware.get_hooks()."""
        return merge_hooks(self._config.hooks, self._config.middleware)


def build_tools_mcp_server(tools: tuple[Any, ...]) -> Any:
    """Create an in-process MCP server from a ToolDefinition tuple."""
    from swarmline.runtime.sdk_tools import create_mcp_server, mcp_tool

    sdk_tools = []
    for td in tools:
        adapted = _adapt_handler(td.handler)
        sdk_t = mcp_tool(td.name, td.description, td.parameters)(adapted)
        sdk_tools.append(sdk_t)

    return create_mcp_server("agent_tools", tools=sdk_tools)




def _adapt_handler(handler: Any) -> Any:
    """Adapt a user handler to the SDK MCP handler contract.

    SDK expects: handler(args_dict) -> {"content": [{"type": "text", "text": "..."}]}
    User handler: handler(a=1, b=2) -> "result" or any type.
    """

    async def adapted(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await handler(**args)
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "is_error": True,
            }

        # If the handler already returned MCP format - passthrough
        if isinstance(result, dict) and "content" in result:
            return result

        # Wrap into MCP format
        return {
            "content": [{"type": "text", "text": str(result)}],
        }

    return adapted


async def apply_before_query(
    prompt: str,
    middleware: tuple[Any, ...],
    config: Any,
) -> str:
    """Apply the middleware.before_query chain to the prompt."""
    for mw in middleware:
        prompt = await mw.before_query(prompt, config)
    return prompt


async def collect_stream_result(stream: AsyncIterator[Any]) -> dict[str, Any]:
    """Collect Result fields from a stream of StreamEvent-like objects.

    Used in Agent.query() and Conversation.say() for consistent
    collection of text/session_id/cost/usage/structured_output/error from the stream.
    """
    text = ""
    session_id = None
    total_cost_usd = None
    usage = None
    structured_output = None
    native_metadata = None
    new_messages = None
    error = None

    async for event in stream:
        etype = event.type
        if etype == "text_delta":
            text += event.text
        elif etype in {"done", "final"}:
            payload = getattr(event, "data", {}) if hasattr(event, "data") else {}
            text = getattr(event, "text", None) or payload.get("text", text)
            session_id = getattr(event, "session_id", None)
            if session_id is None:
                session_id = payload.get("session_id")
            total_cost_usd = getattr(event, "total_cost_usd", None)
            if total_cost_usd is None:
                total_cost_usd = payload.get("total_cost_usd")
            usage = getattr(event, "usage", None)
            if usage is None:
                usage = payload.get("usage")
            structured_output = getattr(event, "structured_output", None)
            if structured_output is None:
                structured_output = payload.get("structured_output")
            native_metadata = getattr(event, "native_metadata", None)
            if native_metadata is None:
                native_metadata = payload.get("native_metadata")
            new_messages = getattr(event, "new_messages", None)
            if new_messages is None:
                new_messages = payload.get("new_messages")
        elif etype == "error":
            error = event.text or "Unknown error"

    return {
        "text": text,
        "session_id": session_id,
        "total_cost_usd": total_cost_usd,
        "usage": usage,
        "structured_output": structured_output,
        "native_metadata": native_metadata,
        "new_messages": new_messages,
        "error": error,
    }


def _runtime_message_from_payload(payload: Any) -> Message:
    """Normalize runtime payload into Message."""
    from swarmline.runtime.types import Message

    if isinstance(payload, Message):
        return payload
    if isinstance(payload, dict):
        return Message(**payload)
    raise TypeError(f"Unsupported runtime message payload: {type(payload)!r}")


def _runtime_messages_from_payloads(payloads: Any) -> list[Message]:
    """Normalize runtime new_messages payload into Message list."""
    if not payloads:
        return []

    return [_runtime_message_from_payload(payload) for payload in payloads]


class _RuntimeEventAdapter:
    """Adapter from RuntimeEvent to a StreamEvent-like interface."""

    def __init__(self, event: Any) -> None:
        self._event = event
        etype = event.type
        data = event.data or {}

        # Map RuntimeEvent to StreamEvent types
        if etype == "assistant_delta":
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

        # Defaults for attributes that may not be set
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
        self.new_messages: list[Any] = []
