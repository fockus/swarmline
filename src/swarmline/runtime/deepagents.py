"""Deepagents module."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from swarmline.runtime.deepagents_builtins import (
    DEEPAGENTS_NATIVE_BUILTIN_TOOLS,
    build_native_notice,
    build_portable_notice,
    filter_native_builtin_tools,
    split_native_builtin_tools,
)
from swarmline.runtime.deepagents_hitl import validate_hitl_config
from swarmline.runtime.deepagents_langchain import (
    build_langchain_messages,
    check_langchain_available,
    stream_langchain_runtime_events,
)
from swarmline.runtime.deepagents_memory import (
    build_native_invocation,
    build_native_state_notice,
    validate_native_state_config,
)
from swarmline.runtime.deepagents_models import (
    DeepAgentsModelError,
    build_deepagents_chat_model,
)
from swarmline.runtime.deepagents_native import (
    build_deepagents_graph,
    stream_deepagents_graph_events,
    validate_native_backend_config,
)
from swarmline.runtime.deepagents_tools import create_langchain_tool
from swarmline.runtime.mcp_bridge import McpBridge
from swarmline.runtime.thin.mcp_client import parse_mcp_tool_name
from swarmline.runtime.structured_output import (
    append_structured_output_instruction,
    extract_structured_output,
)
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
    TurnMetrics,
)

_log = logging.getLogger(__name__)

_DEEPAGENTS_BUILTIN_TOOLS = DEEPAGENTS_NATIVE_BUILTIN_TOOLS
__all__ = ["DeepAgentsRuntime", "_check_langchain_available", "create_langchain_tool"]


def _check_langchain_available() -> RuntimeErrorData | None:
    """Check langchain available."""
    return check_langchain_available()


class DeepAgentsRuntime:
    """Deep Agents Runtime implementation."""

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        tool_executors: dict[str, Callable] | None = None,
        mcp_servers: dict[str, Any] | None = None,
    ) -> None:
        """Init."""
        self._config = config or RuntimeConfig(runtime_name="deepagents")
        self._tool_executors = tool_executors or {}
        self._mcp_bridge = McpBridge(mcp_servers) if mcp_servers else None

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Run."""
        dep_error = _check_langchain_available()
        if dep_error:
            yield RuntimeEvent.error(dep_error)
            return

        effective_config = config or self._config
        effective_system_prompt = append_structured_output_instruction(
            system_prompt,
            effective_config.output_format,
        )

        requested_tools = list(active_tools)
        selected_tools = self.select_active_tools(
            active_tools,
            feature_mode=effective_config.feature_mode,
            allow_native_features=effective_config.allow_native_features,
        )

        # Discover MCP tools and merge
        if self._mcp_bridge is not None:
            try:
                mcp_tools = await self._mcp_bridge.discover_all_tools()
                selected_tools = list(selected_tools) + mcp_tools
                # Register MCP executors
                for spec in mcp_tools:
                    parsed = parse_mcp_tool_name(spec.name)
                    if parsed is not None:
                        server_id, tool_name = parsed
                        self._tool_executors[spec.name] = (
                            self._mcp_bridge.create_tool_executor(server_id, tool_name)
                        )
            except Exception as exc:
                _log.warning("MCP discovery failed, tools unavailable: %s", exc)

        full_text = ""
        tool_calls: list[dict[str, Any]] = []
        new_messages: list[Message] = []

        try:
            stream = self._stream_langchain
            final_session_id = None
            final_native_metadata = None
            if self._should_use_native_path(effective_config):
                state_error = validate_native_state_config(
                    effective_config.native_config
                )
                if state_error:
                    yield RuntimeEvent.error(state_error)
                    return

                hitl_error = validate_hitl_config(effective_config.native_config)
                if hitl_error:
                    yield RuntimeEvent.error(hitl_error)
                    return

                native_selection = split_native_builtin_tools(selected_tools)
                backend_error = validate_native_backend_config(
                    native_tool_names=native_selection.native_tool_names,
                    native_config=effective_config.native_config,
                )
                if backend_error:
                    yield RuntimeEvent.error(backend_error)
                    return

                notice = build_native_notice(
                    requested_tools,
                    feature_mode=effective_config.feature_mode,
                )
                if notice:
                    yield RuntimeEvent.status(notice)
                selected_tools = native_selection.custom_tools
                lc_messages = self._build_lc_messages(
                    messages,
                    effective_system_prompt,
                    include_system_prompt=False,
                )
                input_payload, run_config, final_native_metadata = (
                    build_native_invocation(
                        messages=lc_messages,
                        native_config=effective_config.native_config,
                    )
                )
                final_session_id = final_native_metadata.get("thread_id")
                state_notice = build_native_state_notice(final_native_metadata)
                if state_notice:
                    yield RuntimeEvent.native_notice(
                        state_notice,
                        metadata=final_native_metadata,
                    )
                stream = self._stream_native
            else:
                notice = build_portable_notice(requested_tools)
                if notice:
                    yield RuntimeEvent.status(notice)

            async for event in stream(
                messages=messages,
                system_prompt=effective_system_prompt,
                tools=selected_tools,
                model=effective_config.model,
                base_url=effective_config.base_url,
                native_config=effective_config.native_config,
                input_payload=locals().get("input_payload"),
                run_config=locals().get("run_config"),
            ):
                yield event
                if event.type == "assistant_delta":
                    full_text += str(event.data.get("text", ""))
                elif event.type == "tool_call_started":
                    tool_name = str(event.data.get("name", ""))
                    correlation_id = str(event.data.get("correlation_id", ""))
                    tool_args = event.data.get("args", {})
                    new_messages.append(
                        Message(
                            role="assistant",
                            content="",
                            tool_calls=[
                                {
                                    "id": correlation_id,
                                    "name": tool_name,
                                    "args": tool_args
                                    if isinstance(tool_args, dict)
                                    else {},
                                    "type": "tool_call",
                                }
                            ],
                            metadata={
                                "correlation_id": correlation_id,
                                "tool_name": tool_name,
                            },
                        )
                    )
                elif event.type == "tool_call_finished":
                    tool_calls.append(event.data)
                    new_messages.append(
                        Message(
                            role="tool",
                            content=str(event.data.get("result_summary", "")),
                            name=str(event.data.get("name", "")) or None,
                            metadata={
                                "correlation_id": str(
                                    event.data.get("correlation_id", "")
                                ),
                            },
                        )
                    )

        except DeepAgentsModelError as e:
            yield RuntimeEvent.error(e.error)
            return
        except Exception as e:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=f"Ошибка LangChain: {e}",
                    recoverable=False,
                )
            )
            return

        new_messages.append(Message(role="assistant", content=full_text))

        yield RuntimeEvent.final(
            text=full_text,
            new_messages=new_messages,
            metrics=TurnMetrics(
                model=effective_config.model,
                tool_calls_count=len(tool_calls),
            ),
            session_id=final_session_id,
            structured_output=extract_structured_output(
                full_text,
                effective_config.output_format,
            ),
            native_metadata=final_native_metadata,
        )

    def _build_lc_messages(
        self,
        messages: list[Message],
        system_prompt: str,
        *,
        include_system_prompt: bool = True,
    ) -> list[Any]:
        """Build lc messages."""
        return build_langchain_messages(
            messages,
            system_prompt,
            include_system_prompt=include_system_prompt,
        )

    def _build_llm(self, model: str, base_url: str | None = None) -> Any:
        """Create provider-specific chat model via separate resolver."""
        return build_deepagents_chat_model(model, base_url=base_url)

    def _should_use_native_path(self, config: RuntimeConfig) -> bool:
        """Should use native path."""
        return config.is_native_mode

    async def _stream_native(
        self,
        messages: list[Message],
        system_prompt: str,
        tools: list[ToolSpec],
        model: str,
        base_url: str | None = None,
        native_config: dict[str, Any] | None = None,
        input_payload: Any = None,
        run_config: dict[str, Any] | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Stream native."""
        native_config = native_config or {}
        graph = build_deepagents_graph(
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            tool_executors=self._tool_executors,
            base_url=base_url,
            interrupt_on=native_config.get("interrupt_on"),
            checkpointer=native_config.get("checkpointer"),
            store=native_config.get("store"),
            backend=native_config.get("backend"),
            memory=native_config.get("memory"),
            subagents=native_config.get("subagents"),
            skills=native_config.get("skills"),
            middleware=native_config.get("middleware"),
            agent_name=native_config.get("agent_name"),
        )
        async for event in stream_deepagents_graph_events(
            graph=graph,
            input_payload=input_payload or {"messages": []},
            run_config=run_config,
        ):
            yield event

    async def _stream_langchain(
        self,
        messages: list[Message],
        system_prompt: str,
        tools: list[ToolSpec],
        model: str,
        base_url: str | None = None,
        native_config: dict[str, Any] | None = None,
        input_payload: Any = None,
        run_config: dict[str, Any] | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Stream langchain."""
        lc_messages = self._build_lc_messages(messages, system_prompt)
        lc_tools = [
            create_langchain_tool(spec, self._tool_executors.get(spec.name))
            for spec in tools
        ]
        llm = self._build_llm(model, base_url)
        runnable = llm.bind_tools(lc_tools) if lc_tools else llm

        async for event in stream_langchain_runtime_events(
            runnable=runnable,
            lc_messages=lc_messages,
        ):
            yield event

    async def cleanup(self) -> None:
        """Cleanup."""

    @staticmethod
    def filter_builtin_tools(tools: list[ToolSpec]) -> list[ToolSpec]:
        """Filter builtin tools."""
        return filter_native_builtin_tools(tools)

    @staticmethod
    def select_active_tools(
        tools: list[ToolSpec],
        *,
        feature_mode: str,
        allow_native_features: bool = False,
    ) -> list[ToolSpec]:
        """Select active tools."""
        if allow_native_features or feature_mode in {"hybrid", "native_first"}:
            return list(tools)
        return DeepAgentsRuntime.filter_builtin_tools(tools)
