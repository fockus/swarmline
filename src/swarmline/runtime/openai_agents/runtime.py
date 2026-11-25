"""OpenAIAgentsRuntime - wrapper around OpenAI Agents SDK for AgentRuntime v1 contract.

Logic:
1. Create an OpenAI Agent with instructions (system_prompt) and tools
2. Optionally attach Codex and/or Swarmline MCP servers
3. Run via Runner.run_streamed()
4. Convert stream events → RuntimeEvent
5. Build final event with accumulated text, structured output, usage, metrics
"""

from __future__ import annotations

import importlib
import os
from collections.abc import AsyncIterator
from typing import Any, Literal, cast

import structlog

from swarmline.network_safety import validate_http_endpoint_url
from swarmline.observability.redaction import redact_secrets
from swarmline.runtime.openai_agents.event_mapper import (
    StreamEventMapper,
    map_run_error,
)
from swarmline.runtime.openai_agents.tool_bridge import (
    ToolExecutorFn,
    toolspecs_to_agent_tools,
)
from swarmline.runtime.openai_agents.types import OpenAIAgentsConfig
from swarmline.runtime.structured_output import (
    append_structured_output_instruction,
    try_resolve_structured_output,
)
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ThinkingConfig,
    ToolSpec,
    TurnMetrics,
)

_log = structlog.get_logger(component="openai_agents_runtime")

# Providers that never require a real API key (local OpenAI-compatible servers)
_KEYLESS_PROVIDERS = frozenset({"ollama", "local"})


def _safe_int(value: Any) -> int:
    """Coerce a usage counter to int, defensively."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _reasoning_effort_from_thinking(
    thinking: ThinkingConfig,
) -> Literal["low", "medium", "high"]:
    """Map RuntimeConfig.thinking.budget_tokens -> OpenAI reasoning effort.

    Local mirror of ``pi_sdk.runtime._thinking_level_from_runtime_config``'s
    thresholds (only 2 call sites repo-wide; not extracted to a shared
    helper -- keep both in sync if the mapping ever changes):

      < 4_000   -> "low"
      < 16_000  -> "medium"
      otherwise -> "high"
    """
    if thinking.budget_tokens < 4_000:
        return "low"
    if thinking.budget_tokens < 16_000:
        return "medium"
    return "high"


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
        mcp_servers: dict[str, Any] | None = None,
    ) -> None:
        self._config = config or RuntimeConfig(runtime_name="openai_agents")
        self._agents_config = agents_config or OpenAIAgentsConfig()
        self._tool_executor = tool_executor
        self._mcp_servers = dict(mcp_servers or {})
        self._cancel_requested = False
        self._custom_client: Any = None

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
        model_name = effective_config.model or self._agents_config.model
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

        # B1: provider override (base_url/api_key and provider:model slugs)
        try:
            model, provider_error = self._resolve_model(
                agents_mod, effective_config, model_name
            )
        except Exception as exc:
            _log.error(
                "openai_agents_provider_resolution_failed",
                model=model_name,
                exc_type=type(exc).__name__,
                error=redact_secrets(str(exc)),
            )
            yield map_run_error(exc)
            return
        if provider_error is not None:
            yield provider_error
            return

        # Convert Swarmline tools to OpenAI Agent tools
        agent_tools = toolspecs_to_agent_tools(
            active_tools, executor=self._tool_executor
        )

        # D1: structured output - native output_type, or prompt-injected schema
        output_type = effective_config.output_type
        output_format = effective_config.output_format
        effective_prompt = system_prompt
        if output_type is None and output_format:
            effective_prompt = append_structured_output_instruction(
                system_prompt, output_format
            )

        # Build MCP servers list (Codex + generic Swarmline specs)
        mcp_servers: list[Any] = []
        if self._agents_config.codex_enabled:
            mcp_servers.extend(self._build_codex_mcp())
        generic_servers: list[Any] = []
        if self._mcp_servers:
            try:
                generic_servers = self._build_generic_mcp_servers()
            except Exception as exc:
                _log.error(
                    "mcp_server_spec_invalid",
                    error=redact_secrets(str(exc)),
                )
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message=f"Invalid MCP server configuration: {redact_secrets(str(exc))}",
                        recoverable=False,
                    )
                )
                return
        mcp_servers.extend(generic_servers)

        # Create Agent
        agent_kwargs: dict[str, Any] = {
            "name": "swarmline-agent",
            "instructions": effective_prompt,
            "model": model,
            "tools": agent_tools,
            "mcp_servers": mcp_servers,
        }
        if output_type is not None:
            agent_kwargs["output_type"] = output_type
        # I-098a (finding 3): RuntimeConfig.thinking arrives here (validator
        # declares thinking_stream="native" for openai_agents) but was never
        # consumed -- wire it into a reasoning effort, the closest OpenAI
        # Agents SDK equivalent. openai is a hard dependency of the agents
        # SDK, so it is always importable once agents_mod itself imported.
        if effective_config.thinking is not None:
            from openai.types.shared import Reasoning

            ModelSettings = getattr(agents_mod, "ModelSettings")
            agent_kwargs["model_settings"] = ModelSettings(
                reasoning=Reasoning(
                    effort=_reasoning_effort_from_thinking(effective_config.thinking)
                )
            )
        agent = Agent(**agent_kwargs)

        # B2: generic MCP servers need an async connect before Runner streaming
        connected_servers: list[Any] = []
        try:
            for server in generic_servers:
                await server.connect()
                connected_servers.append(server)
        except Exception as exc:
            await self._cleanup_mcp_servers(connected_servers)
            _log.error(
                "mcp_server_connect_failed",
                exc_type=type(exc).__name__,
                error=redact_secrets(str(exc)),
            )
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=f"Failed to connect MCP server: {redact_secrets(str(exc))}",
                    recoverable=False,
                )
            )
            return

        # Stream execution
        full_text = ""
        tool_calls_count = 0
        new_messages: list[Message] = []
        event_mapper = StreamEventMapper()

        result: Any = None
        try:
            result = Runner.run_streamed(
                starting_agent=agent,
                input=cast(Any, agent_input),
                max_turns=self._agents_config.max_turns,
            )
            async for event in result.stream_events():
                if self._cancel_requested:
                    # Stop the SDK's background run task — without this the
                    # model call keeps running after we abandon the stream.
                    self._cancel_run_result(result)
                    yield RuntimeEvent.error(
                        RuntimeErrorData(
                            kind="cancelled",
                            message="Run cancelled by user.",
                            recoverable=False,
                        )
                    )
                    return

                runtime_event = event_mapper.map_event(event)
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
        finally:
            if self._cancel_requested:
                self._cancel_run_result(result)
            await self._cleanup_mcp_servers(connected_servers)
            await self._close_custom_client()

        # Build new_messages
        if full_text:
            new_messages.append(Message(role="assistant", content=full_text))

        # D1: resolve structured output for the final event
        structured_output, structured_error = self._resolve_structured_output(
            result, full_text, output_format, output_type
        )
        if structured_error:
            _log.warning(
                "structured_output_parse_failed",
                error=redact_secrets(structured_error),
            )

        # D2: usage from RunResultStreaming.context_wrapper.usage
        usage_obj = getattr(getattr(result, "context_wrapper", None), "usage", None)
        tokens_in = _safe_int(getattr(usage_obj, "input_tokens", 0))
        tokens_out = _safe_int(getattr(usage_obj, "output_tokens", 0))
        usage_payload: dict[str, Any] | None = None
        if usage_obj is not None:
            usage_payload = {
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
            }
            total_tokens = _safe_int(getattr(usage_obj, "total_tokens", 0))
            if total_tokens:
                usage_payload["total_tokens"] = total_tokens
            requests = _safe_int(getattr(usage_obj, "requests", 0))
            if requests:
                usage_payload["requests"] = requests

        # Final event
        metrics = TurnMetrics(
            tool_calls_count=tool_calls_count,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model_name,
        )
        yield RuntimeEvent.final(
            text=full_text,
            new_messages=new_messages,
            metrics=metrics,
            usage=usage_payload,
            structured_output=structured_output,
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

    # ------------------------------------------------------------------
    # B1: provider override
    # ------------------------------------------------------------------

    def _resolve_model(
        self,
        agents_mod: Any,
        config: RuntimeConfig,
        model_name: str,
    ) -> tuple[Any, RuntimeEvent | None]:
        """Resolve the Agent model honoring base_url/api_key and provider slugs.

        Returns ``(model, error_event)``. When ``error_event`` is not None the
        caller must yield it and stop (e.g. anthropic/google slugs which the
        OpenAI Agents SDK cannot serve).
        """
        base_url = config.base_url
        api_key = config.api_key

        if ":" in model_name:
            from swarmline.runtime.provider_resolver import resolve_provider

            resolved = resolve_provider(model_name, base_url=base_url, api_key=api_key)
            if resolved.sdk_type != "openai_compat":
                return None, RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="capability_unsupported",
                        message=(
                            f"runtime='openai_agents' only supports OpenAI-compatible "
                            f"providers; got provider '{resolved.provider}' from model "
                            f"'{model_name}'. Use runtime='thin' or runtime='claude_sdk' "
                            f"for {resolved.provider} models."
                        ),
                        recoverable=False,
                    )
                )
            effective_key = resolved.api_key or self._env_api_key(resolved.provider)
            return (
                self._build_openai_model(
                    agents_mod,
                    model_id=resolved.model_id,
                    base_url=resolved.base_url,
                    api_key=effective_key,
                ),
                None,
            )

        if base_url or api_key:
            return (
                self._build_openai_model(
                    agents_mod,
                    model_id=model_name,
                    base_url=base_url,
                    api_key=api_key,
                ),
                None,
            )

        # No overrides: pass the model name through (SDK default OpenAI client)
        return model_name, None

    def _build_openai_model(
        self,
        agents_mod: Any,
        *,
        model_id: str,
        base_url: str | None,
        api_key: str | None,
    ) -> Any:
        """Build an OpenAIChatCompletionsModel bound to a custom AsyncOpenAI client."""
        openai_mod = importlib.import_module("openai")
        AsyncOpenAI = getattr(openai_mod, "AsyncOpenAI")
        client_kwargs: dict[str, Any] = {}
        if base_url:
            client_kwargs["base_url"] = base_url
        if api_key:
            client_kwargs["api_key"] = api_key
        client = AsyncOpenAI(**client_kwargs)
        # Tracked so run() can close the httpx pool deterministically.
        self._custom_client = client
        OpenAIChatCompletionsModel = getattr(agents_mod, "OpenAIChatCompletionsModel")
        return OpenAIChatCompletionsModel(model=model_id, openai_client=client)

    @staticmethod
    def _cancel_run_result(result: Any) -> None:
        """Cancel the SDK's background run task (best effort)."""
        if result is None:
            return
        cancel = getattr(result, "cancel", None)
        if cancel is None:
            return
        try:
            cancel()
        except Exception as exc:
            _log.warning(
                "run_result_cancel_failed",
                exc_type=type(exc).__name__,
                error=redact_secrets(str(exc)),
            )

    async def _close_custom_client(self) -> None:
        """Close the provider-override AsyncOpenAI client, if one was built."""
        client = self._custom_client
        self._custom_client = None
        if client is None:
            return
        close = getattr(client, "close", None)
        if close is None:
            return
        try:
            await close()
        except Exception as exc:
            _log.warning(
                "custom_client_close_failed",
                exc_type=type(exc).__name__,
                error=redact_secrets(str(exc)),
            )

    @staticmethod
    def _env_api_key(provider: str) -> str | None:
        """Resolve an API key from environment for an OpenAI-compatible provider.

        Checks ``{PROVIDER}_API_KEY`` first (e.g. OPENROUTER_API_KEY), then the
        back-compat ``OPENAI_API_KEY``. Local servers get a placeholder key.
        """
        env_key = os.environ.get(f"{provider.upper()}_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
        if env_key:
            return env_key
        if provider in _KEYLESS_PROVIDERS:
            return "local"
        return None

    # ------------------------------------------------------------------
    # B2: generic MCP servers
    # ------------------------------------------------------------------

    def _build_generic_mcp_servers(self) -> list[Any]:
        """Map Swarmline MCP server specs to OpenAI Agents SDK MCP servers.

        Spec shapes mirror ``options_builder._spec_to_sdk_config``:
        ``{"command": ..., "args": ..., "env": ...}`` → stdio;
        ``{"type": "http"|"sse", "url": ...}`` / ``{"url": ...}`` / bare URL
        string → streamable-http / SSE (with SSRF validation).
        """
        mcp_mod = importlib.import_module("agents.mcp")
        return [
            self._spec_to_mcp_server(mcp_mod, name, spec)
            for name, spec in self._mcp_servers.items()
        ]

    @staticmethod
    def _spec_field(spec: Any, key: str, default: Any = None) -> Any:
        """Read a field from a dict-style or attribute-style MCP spec."""
        if isinstance(spec, dict):
            return spec.get(key, default)
        return getattr(spec, key, default)

    def _spec_to_mcp_server(self, mcp_mod: Any, name: str, spec: Any) -> Any:
        """Convert one Swarmline MCP server spec to an SDK MCP server instance."""
        if isinstance(spec, str):
            spec = {"url": spec}

        command = self._spec_field(spec, "command")
        if command:
            params: dict[str, Any] = {"command": command}
            args = self._spec_field(spec, "args")
            if args:
                params["args"] = list(args)
            env = self._spec_field(spec, "env")
            if env:
                params["env"] = dict(env)
            MCPServerStdio = getattr(mcp_mod, "MCPServerStdio")
            return MCPServerStdio(name=name, params=cast(Any, params))

        url = self._spec_field(spec, "url")
        if not isinstance(url, str) or not url:
            raise ValueError(
                f"MCP server '{name}' spec must define 'command' (stdio) or 'url' (http/sse)"
            )
        rejection = validate_http_endpoint_url(
            url,
            allow_private_network=bool(
                self._spec_field(spec, "allow_private_network", False)
            ),
            allow_insecure_http=bool(
                self._spec_field(spec, "allow_insecure_http", False)
            ),
        )
        if rejection:
            raise ValueError(f"Unsafe MCP server URL for '{name}': {rejection}")

        transport = str(
            self._spec_field(spec, "type")
            or self._spec_field(spec, "transport")
            or "http"
        ).lower()
        if transport == "sse":
            MCPServerSse = getattr(mcp_mod, "MCPServerSse")
            return MCPServerSse(name=name, params=cast(Any, {"url": url}))
        MCPServerStreamableHttp = getattr(mcp_mod, "MCPServerStreamableHttp")
        return MCPServerStreamableHttp(name=name, params=cast(Any, {"url": url}))

    @staticmethod
    async def _cleanup_mcp_servers(servers: list[Any]) -> None:
        """Cleanup connected MCP servers, swallowing per-server failures."""
        for server in servers:
            cleanup = getattr(server, "cleanup", None)
            if cleanup is None:
                continue
            try:
                await cleanup()
            except Exception as exc:
                _log.warning(
                    "mcp_server_cleanup_failed",
                    server=getattr(server, "name", "unknown"),
                    error=redact_secrets(str(exc)),
                )

    # ------------------------------------------------------------------
    # D1: structured output resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_structured_output(
        result: Any,
        full_text: str,
        output_format: dict[str, Any] | None,
        output_type: type | None,
    ) -> tuple[Any, str | None]:
        """Resolve structured output from the streamed result / final text."""
        if output_type is not None:
            candidate = getattr(result, "final_output", None)
            if isinstance(candidate, output_type) and not isinstance(candidate, str):
                return candidate, None
            source = full_text or (candidate if isinstance(candidate, str) else "")
            if source:
                return try_resolve_structured_output(source, output_format, output_type)
            return None, "no output text to validate against output_type"
        if output_format:
            return try_resolve_structured_output(full_text, output_format, None)
        return None, None
