"""Native upstream DeepAgents graph adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent, ToolSpec


def build_deepagents_chat_model(
    raw_model: str | None,
    *,
    base_url: str | None = None,
) -> Any:
    """Lazy wrapper around the provider-aware model builder."""
    from swarmline.runtime.deepagents_models import (
        build_deepagents_chat_model as _build_deepagents_chat_model,
    )

    return _build_deepagents_chat_model(raw_model, base_url=base_url)


def create_langchain_tool(spec: ToolSpec, executor: Callable | None) -> Any:
    """Lazy wrapper around the LangChain tool factory."""
    from swarmline.runtime.deepagents_tools import (
        create_langchain_tool as _create_langchain_tool,
    )

    return _create_langchain_tool(spec, executor)


def _extract_chunk_text(content: Any) -> str:
    """Extract text from LangChain/DeepAgents chunk content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "".join(part for part in parts if part)
    return ""


def build_deepagents_graph(
    *,
    model: str,
    system_prompt: str,
    tools: list[ToolSpec],
    tool_executors: dict[str, Callable],
    base_url: str | None = None,
    interrupt_on: dict[str, Any] | None = None,
    checkpointer: Any = None,
    store: Any = None,
    backend: Any = None,
    memory: list[str] | None = None,
    subagents: list[dict[str, Any]] | None = None,
    skills: list[dict[str, Any]] | None = None,
    middleware: list[Any] | None = None,
    agent_name: str | None = None,
) -> Any:
    """Build a native DeepAgents graph via upstream create_deep_agent()."""
    from swarmline.runtime.deepagents_builtins import split_native_builtin_tools
    from deepagents import create_deep_agent  # type: ignore[import-not-found]

    llm = build_deepagents_chat_model(model, base_url=base_url)
    selection = split_native_builtin_tools(tools)
    lc_tools = [
        create_langchain_tool(spec, tool_executors.get(spec.name))
        for spec in selection.custom_tools
    ]
    kwargs: dict[str, Any] = {
        "model": llm,
        "tools": lc_tools,
        "system_prompt": system_prompt,
    }
    if interrupt_on is not None:
        kwargs["interrupt_on"] = interrupt_on
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
    if store is not None:
        kwargs["store"] = store
    if backend is not None:
        kwargs["backend"] = backend
    if memory is not None:
        kwargs["memory"] = memory
    if subagents is not None:
        kwargs["subagents"] = subagents
    if skills is not None:
        kwargs["skills"] = skills
    if middleware is not None:
        kwargs["middleware"] = middleware
    if agent_name is not None:
        kwargs["name"] = agent_name

    return create_deep_agent(
        **kwargs,
    )


def validate_native_backend_config(
    *,
    native_tool_names: list[str],
    native_config: dict[str, Any],
) -> RuntimeErrorData | None:
    """Require an explicit backend for native built-ins instead of a silent StateBackend fallback."""
    if not native_tool_names or native_config.get("backend") is not None:
        return None

    return RuntimeErrorData(
        kind="capability_unsupported",
        message=(
            "DeepAgents native built-ins require native_config['backend']; "
            "without it, upstream uses StateBackend with an ephemeral filesystem."
        ),
        recoverable=False,
        details={"native_tools": list(native_tool_names)},
    )


async def stream_deepagents_graph_events(
    *,
    graph: Any,
    input_payload: Any,
    run_config: dict[str, Any] | None = None,
) -> AsyncIterator[RuntimeEvent]:
    """Normalize upstream graph events into RuntimeEvent."""
    from swarmline.runtime.deepagents_hitl import build_interrupt_events

    tool_correlation: dict[str, str] = {}
    saw_text = False

    stream = (
        graph.astream_events(input_payload, run_config, version="v2")
        if run_config
        else graph.astream_events(input_payload, version="v2")
    )

    async for event in stream:
        kind = event.get("event", "")

        if kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            text = _extract_chunk_text(getattr(chunk, "content", None))
            if text:
                saw_text = True
                yield RuntimeEvent.assistant_delta(text)

        elif kind == "on_chat_model_end" and not saw_text:
            output = event.get("data", {}).get("output")
            text = _extract_chunk_text(getattr(output, "content", None))
            if text:
                saw_text = True
                yield RuntimeEvent.assistant_delta(text)

        elif kind == "on_chain_stream":
            chunk = event.get("data", {}).get("chunk")
            if isinstance(chunk, dict):
                for interrupt_event in build_interrupt_events(chunk):
                    yield interrupt_event

        elif kind == "on_tool_start":
            tool_name = event.get("name", "")
            tool_input = event.get("data", {}).get("input", {})
            run_id = event.get("run_id", "")
            started_event = RuntimeEvent.tool_call_started(
                name=tool_name,
                args=tool_input if isinstance(tool_input, dict) else {},
            )
            correlation_id = started_event.data.get("correlation_id", "")
            if run_id:
                tool_correlation[run_id] = correlation_id
            yield started_event

        elif kind == "on_tool_end":
            tool_name = event.get("name", "")
            run_id = event.get("run_id", "")
            correlation_id = tool_correlation.pop(run_id, run_id[:8])
            output = event.get("data", {}).get("output", "")
            yield RuntimeEvent.tool_call_finished(
                name=tool_name,
                correlation_id=correlation_id,
                result_summary=str(output)[:500] if output else "",
            )
