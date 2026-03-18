"""Conversation - explicit multi-turn dialog management."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, cast

from cognitia.agent.result import Result
from cognitia.runtime.types import Message

if TYPE_CHECKING:
    from cognitia.agent.agent import Agent


logger = logging.getLogger(__name__)


class Conversation:
    """Multi-turn conversation with Agent.

    Manages message history and runtime lifecycle.
    - claude_sdk: warm subprocess (continue_conversation)
    - thin/deepagents: accumulated messages → AgentRuntime.run()
    """

    def __init__(
        self,
        agent: Agent,
        session_id: str | None = None,
    ) -> None:
        self._agent = agent
        self._session_id = session_id or uuid.uuid4().hex
        self._history: list[Message] = []
        self._adapter: Any = None  # RuntimeAdapter for claude_sdk
        self._connected = False

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def history(self) -> list[Message]:
        return list(self._history)

    async def say(self, prompt: str) -> Result:
        """Send a message and get a response."""
        # Apply middleware before_query
        from cognitia.agent.agent import apply_before_query

        effective_prompt = await apply_before_query(
            prompt,
            self._agent.config.middleware,
            self._agent.config,
        )

        self._history.append(Message(role="user", content=effective_prompt))

        # Execute + collect
        from cognitia.agent.agent import collect_stream_result, _runtime_messages_from_payloads

        collected = await collect_stream_result(self._execute(effective_prompt))
        result_payload = dict(collected)
        new_messages_payload = result_payload.pop("new_messages", None)
        has_error = result_payload["error"] is not None

        new_messages = _runtime_messages_from_payloads(new_messages_payload)
        if not has_error and new_messages:
            self._history.extend(new_messages)
        elif not has_error and result_payload["text"]:
            self._history.append(Message(role="assistant", content=result_payload["text"]))

        # Conversation always fills session_id
        if not result_payload["session_id"]:
            result_payload["session_id"] = self._session_id

        result = Result(**result_payload)

        # Apply middleware after_result
        for mw in self._agent.config.middleware:
            result = await mw.after_result(result)

        if new_messages_payload is not None:
            object.__setattr__(result, "new_messages", new_messages_payload)

        return result

    async def stream(self, prompt: str) -> AsyncIterator[Any]:
        """Streaming multi-turn reply."""
        from cognitia.agent.agent import apply_before_query

        effective_prompt = await apply_before_query(
            prompt,
            self._agent.config.middleware,
            self._agent.config,
        )

        self._history.append(Message(role="user", content=effective_prompt))

        full_text = ""
        final_new_messages: list[Message] = []
        saw_error = False
        async for event in self._execute(effective_prompt):
            if event.type == "text_delta":
                full_text += event.text
            elif event.type == "error":
                saw_error = True
            elif event.type in {"done", "final"}:
                from cognitia.agent.agent import _runtime_messages_from_payloads

                payload = getattr(event, "data", {}) if hasattr(event, "data") else {}
                payload_new_messages = getattr(event, "new_messages", None)
                if payload_new_messages is None:
                    payload_new_messages = payload.get("new_messages")
                final_new_messages = _runtime_messages_from_payloads(
                    payload_new_messages
                )
            yield event

        if saw_error:
            return

        if final_new_messages:
            self._history.extend(final_new_messages)
        elif full_text:
            self._history.append(Message(role="assistant", content=full_text))

    async def close(self) -> None:
        """Close the conversation (disconnect the runtime)."""
        if self._adapter is not None and self._connected:
            await self._adapter.disconnect()
            self._connected = False
            self._adapter = None

    async def __aenter__(self) -> Conversation:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # -----------------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------------

    async def _execute(self, prompt: str) -> AsyncIterator[Any]:
        """Route execution by runtime."""
        runtime_name = self._agent.config.runtime

        if runtime_name == "claude_sdk":
            async for event in self._execute_claude_sdk(prompt):
                yield event
        else:
            async for event in self._execute_agent_runtime(prompt, runtime_name):
                yield event

    async def _execute_claude_sdk(self, prompt: str) -> AsyncIterator[Any]:
        """Multi-turn via Claude SDK (warm subprocess)."""
        if self._adapter is None:
            self._adapter = await self._create_adapter()
            self._connected = True

        async for event in self._adapter.stream_reply(prompt):
            yield event

    async def _execute_agent_runtime(self, prompt: str, runtime_name: str) -> AsyncIterator[Any]:
        """Multi-turn via AgentRuntime (accumulated messages)."""
        from cognitia.agent.agent import _ErrorEvent, _RuntimeEventAdapter
        from cognitia.agent.runtime_wiring import build_portable_runtime_plan
        from cognitia.runtime.factory import RuntimeFactory

        runtime_plan = build_portable_runtime_plan(
            self._agent.config,
            runtime_name,
            session_id=self._session_id,
        )
        factory = RuntimeFactory()
        runtime: Any | None = None

        try:
            runtime = factory.create(
                config=runtime_plan.config,
                **runtime_plan.create_kwargs,
            )
            async for event in runtime.run(
                messages=list(self._history),
                system_prompt=self._agent.config.system_prompt,
                active_tools=runtime_plan.active_tools,
            ):
                yield _RuntimeEventAdapter(event)
        except Exception as exc:
            logger.exception("Conversation._execute_agent_runtime error")
            yield _ErrorEvent(str(exc))
        finally:
            if runtime is not None:
                await runtime.cleanup()

    async def _create_adapter(self) -> Any:
        """Create and connect a RuntimeAdapter for claude_sdk."""
        from cognitia.agent.agent import merge_hooks
        from cognitia.hooks.sdk_bridge import registry_to_sdk_hooks
        from cognitia.runtime.adapter import RuntimeAdapter
        from cognitia.runtime.options_builder import ClaudeOptionsBuilder

        config = self._agent.config

        # Merge hooks from middleware + config
        merged_hooks = merge_hooks(config.hooks, config.middleware)

        # Build options
        builder = ClaudeOptionsBuilder(
            cwd=config.cwd,
            override_model=config.resolved_model,
        )

        sdk_mcp_servers = {}

        if config.tools:
            from cognitia.agent.agent import build_tools_mcp_server

            sdk_mcp_servers["__agent_tools__"] = build_tools_mcp_server(config.tools)

        sdk_hooks = None
        if merged_hooks:
            sdk_hooks = registry_to_sdk_hooks(merged_hooks)

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
            max_thinking_tokens=config.max_thinking_tokens,
            fallback_model=config.fallback_model,
            sandbox=cast(Any, config.sandbox),
            env=dict(config.env) if config.env else None,
            include_partial_messages=bool(config.native_config.get("include_partial_messages")),
        )

        adapter = RuntimeAdapter(opts)
        await adapter.connect()
        return adapter

    def _merge_hooks(self) -> Any:
        """Merge hooks from config.hooks + middleware.get_hooks()."""
        from cognitia.agent.agent import merge_hooks

        return merge_hooks(self._agent.config.hooks, self._agent.config.middleware)
