"""OpenAIAgentsRuntime - wrapper around OpenAI Agents SDK for AgentRuntime v1 contract.

Logic:
1. Create an OpenAI Agent with instructions (system_prompt) and tools
2. Optionally attach Codex as MCP server
3. Run via Runner.run_streamed()
4. Convert stream events → RuntimeEvent
5. Build final event with accumulated text and metrics
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator
from typing import Any, cast

import structlog

from swarmline.observability.redaction import redact_secrets
from swarmline.runtime.openai_agents.event_mapper import map_run_error, map_stream_event
from swarmline.runtime.openai_agents.tool_bridge import (
    ToolExecutorFn,
    toolspecs_to_agent_tools,
)
from swarmline.runtime.openai_agents.types import OpenAIAgentsConfig
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
    TurnMetrics,
)

_log = structlog.get_logger(component="openai_agents_runtime")


class OpenAIAgentsRuntime:
    """AgentRuntime wrapper around OpenAI Agents SDK.

    Uses Runner.run_streamed() for streaming execution.
    Optionally attaches Codex as an MCP server for code tasks.
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        agents_config: OpenAIAgentsConfig | None = None,
        tool_executor: ToolExecutorFn | None = None,
    ) -> None:
        self._config = config or RuntimeConfig(runtime_name="openai_agents")
        self._agents_config = agents_config or OpenAIAgentsConfig()
        self._tool_executor = tool_executor
        self._cancel_requested = False

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Execute one turn through OpenAI Agents SDK.

        Creates an Agent, optionally attaches Codex MCP, runs streamed,
        and converts events to RuntimeEvent.
        """
        try:
            agents_mod = importlib.import_module("agents")
        except ImportError:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message="openai-agents not installed. Run: pip install swarmline[openai-agents]",
                    recoverable=False,
                )
            )
            return
        Agent = getattr(agents_mod, "Agent")
        Runner = getattr(agents_mod, "Runner")

        effective_config = config or self._config
        model = effective_config.model or self._agents_config.model
        self._cancel_requested = False

        # Build input: full conversation history for multi-turn support.
        # OpenAI Agents SDK accepts str | list[dict] as input.
        agent_input = self._build_input(messages)
        if not agent_input:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message="No user message found in messages.",
                    recoverable=False,
                )
            )
            return

        # Convert Swarmline tools to OpenAI Agent tools
        agent_tools = toolspecs_to_agent_tools(
            active_tools, executor=self._tool_executor
        )

        # Build MCP servers list
        mcp_servers = []
        if self._agents_config.codex_enabled:
            mcp_servers = self._build_codex_mcp()

        # Create Agent
        agent = Agent(
            name="swarmline-agent",
            instructions=system_prompt,
            model=model,
            tools=agent_tools,
            mcp_servers=mcp_servers,
        )

        # Stream execution
        full_text = ""
        tool_calls_count = 0
        new_messages: list[Message] = []

        try:
            result = Runner.run_streamed(
                starting_agent=agent,
                input=cast(Any, agent_input),
                max_turns=self._agents_config.max_turns,
            )
            async for event in result.stream_events():
                if self._cancel_requested:
                    yield RuntimeEvent.error(
                        RuntimeErrorData(
                            kind="cancelled",
                            message="Run cancelled by user.",
                            recoverable=False,
                        )
                    )
                    return

                runtime_event = map_stream_event(event)
                if runtime_event is not None:
                    if runtime_event.type == "assistant_delta":
                        full_text += runtime_event.data.get("text", "")
                    elif runtime_event.type == "tool_call_started":
                        tool_calls_count += 1
                    yield runtime_event

        except Exception as exc:
            _log.error(
                "openai_agents_run_failed",
                exc_type=type(exc).__name__,
                error=redact_secrets(str(exc)),
            )
            yield map_run_error(exc)
            return

        # Build new_messages
        if full_text:
            new_messages.append(Message(role="assistant", content=full_text))

        # Final event
        metrics = TurnMetrics(
            tool_calls_count=tool_calls_count,
            model=model,
        )
        yield RuntimeEvent.final(
            text=full_text,
            new_messages=new_messages,
            metrics=metrics,
        )

    def cancel(self) -> None:
        """Request cooperative cancellation."""
        self._cancel_requested = True

    async def cleanup(self) -> None:
        """Release resources."""
        self._cancel_requested = False

    async def __aenter__(self) -> OpenAIAgentsRuntime:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.cleanup()

    @staticmethod
    def _build_input(messages: list[Message]) -> str | list[dict[str, str]]:
        """Build input for Runner from Swarmline messages.

        Single user message → plain string (simple case).
        Multiple messages → list of role/content dicts (multi-turn).
        Skips system messages (handled via Agent.instructions).
        Returns empty string if no user messages found.
        """
        conversation = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
            if msg.role in ("user", "assistant") and msg.content
        ]
        if not conversation:
            return ""
        # Single user message → simple string for backward compat
        if len(conversation) == 1 and conversation[0]["role"] == "user":
            return conversation[0]["content"]
        return conversation

    @staticmethod
    def _extract_user_input(messages: list[Message]) -> str:
        """Extract the last user message text.

        .. deprecated:: Use _build_input for multi-turn support.
        """
        for msg in reversed(messages):
            if msg.role == "user" and msg.content:
                return msg.content
        return ""

    def _build_codex_mcp(self) -> list[Any]:
        """Build Codex MCP server config for the Agent.

        Uses codex_sandbox and codex_approval_policy from OpenAIAgentsConfig.
        Passes env vars from config to the MCP server process.
        """
        try:
            mcp_mod = importlib.import_module("agents.mcp")

            cfg = self._agents_config
            params: dict[str, Any] = {
                "command": "npx",
                "args": [
                    "-y",
                    "codex",
                    "mcp-server",
                    "--sandbox",
                    cfg.codex_sandbox,
                    "--approval-policy",
                    cfg.codex_approval_policy,
                ],
            }
            if cfg.env:
                params["env"] = dict(cfg.env)

            MCPServerStdio = getattr(mcp_mod, "MCPServerStdio")
            return [
                MCPServerStdio(
                    name="Codex CLI",
                    params=cast(Any, params),
                    client_session_timeout_seconds=300,
                )
            ]
        except ImportError:
            _log.warning("mcp_server_stdio_unavailable")
            return []
