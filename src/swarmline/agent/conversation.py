"""Conversation - explicit multi-turn dialog management."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from swarmline.agent.result import Result
from swarmline.agent.runtime_dispatch import (
    create_claude_conversation_adapter,
    dispatch_runtime,
    run_portable_runtime,
)
from swarmline.runtime.types import Message

if TYPE_CHECKING:
    from swarmline.agent.agent import Agent
    from swarmline.compaction import CompactionConfig
    from swarmline.protocols.memory import MessageStore


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
        message_store: MessageStore | None = None,
        user_id: str = "default",
        compaction_config: CompactionConfig | None = None,
    ) -> None:
        self._agent = agent
        self._session_id = session_id or uuid.uuid4().hex
        self._history: list[Message] = []
        self._adapter: Any = None  # RuntimeAdapter for claude_sdk
        self._connected = False
        self._message_store = message_store
        self._user_id = user_id
        self._compaction_config = compaction_config

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def history(self) -> list[Message]:
        return list(self._history)

    async def resume(self, session_id: str) -> None:
        """Load conversation history from message_store and optionally compact.

        Raises RuntimeError if no message_store is configured.
        """
        if self._message_store is None:
            raise RuntimeError(
                "Cannot resume: no message_store configured. "
                "Pass message_store to Conversation.__init__."
            )
        self._session_id = session_id
        memory_messages = await self._message_store.get_messages(
            self._user_id, session_id, limit=2**31 - 1,
        )
        self._history = [
            Message.from_memory_message(mm) for mm in memory_messages
        ]
        if self._compaction_config and self._history:
            from swarmline.compaction import ConversationCompactionFilter

            compactor = ConversationCompactionFilter(config=self._compaction_config)
            system_prompt = self._agent.config.system_prompt
            self._history, _ = await compactor.filter(self._history, system_prompt)

    async def say(self, prompt: str) -> Result:
        """Send a message and get a response."""
        # Apply middleware before_query
        from swarmline.agent.agent import apply_before_query

        effective_prompt = await apply_before_query(
            prompt,
            self._agent.config.middleware,
            self._agent.config,
        )

        history_len_before = len(self._history)
        self._history.append(Message(role="user", content=effective_prompt))

        # Execute + collect
        from swarmline.agent.agent import collect_stream_result, _runtime_messages_from_payloads

        collected = await collect_stream_result(self._execute(effective_prompt))
        result_payload = dict(collected)
        new_messages_payload = result_payload.pop("new_messages", None)
        has_error = result_payload["error"] is not None

        new_messages = _runtime_messages_from_payloads(new_messages_payload)
        if not has_error and new_messages:
            self._history.extend(new_messages)
        elif not has_error and result_payload["text"]:
            self._history.append(Message(role="assistant", content=result_payload["text"]))

        # Auto-persist new messages to store
        if self._message_store is not None:
            for msg in self._history[history_len_before:]:
                await self._message_store.save_message(
                    self._user_id,
                    self._session_id,
                    msg.role,
                    msg.content,
                    msg.tool_calls,
                    name=msg.name,
                    metadata=msg.metadata,
                    content_blocks=(
                        [block.to_dict() for block in msg.content_blocks]
                        if msg.content_blocks is not None
                        else None
                    ),
                )

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
        from swarmline.agent.agent import apply_before_query

        effective_prompt = await apply_before_query(
            prompt,
            self._agent.config.middleware,
            self._agent.config,
        )

        history_len_before = len(self._history)
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
                from swarmline.agent.agent import _runtime_messages_from_payloads

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

        # Auto-persist new messages (stream path)
        if self._message_store is not None:
            for msg in self._history[history_len_before:]:
                await self._message_store.save_message(
                    self._user_id,
                    self._session_id,
                    msg.role,
                    msg.content,
                    msg.tool_calls,
                    name=msg.name,
                    metadata=msg.metadata,
                    content_blocks=(
                        [block.to_dict() for block in msg.content_blocks]
                        if msg.content_blocks is not None
                        else None
                    ),
                )

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
        async for event in dispatch_runtime(
            self._agent.config.runtime,
            lambda: self._execute_claude_sdk(prompt),
            lambda runtime_name: self._execute_agent_runtime(prompt, runtime_name),
        ):
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
        from swarmline.agent.agent import _ErrorEvent, _RuntimeEventAdapter
        async for event in run_portable_runtime(
            agent_config=self._agent.config,
            runtime_name=runtime_name,
            messages=list(self._history),
            system_prompt=self._agent.config.system_prompt,
            runtime_factory=self._agent.runtime_factory,
            session_id=self._session_id,
            event_adapter=_RuntimeEventAdapter,
            error_factory=lambda exc: _ErrorEvent(str(exc)),
            logger=logger,
            error_context="Conversation._execute_agent_runtime",
        ):
            yield event

    async def _create_adapter(self) -> Any:
        """Create and connect a RuntimeAdapter for claude_sdk."""
        return await create_claude_conversation_adapter(
            self._agent.config,
            runtime_factory=self._agent.runtime_factory,
        )

    def _merge_hooks(self) -> Any:
        """Merge hooks from config.hooks + middleware.get_hooks()."""
        from swarmline.agent.agent import merge_hooks

        return merge_hooks(self._agent.config.hooks, self._agent.config.middleware)
