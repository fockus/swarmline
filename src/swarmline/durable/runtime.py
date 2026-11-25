"""``DurableRuntime`` — checkpoint-after-step decorator over any ``AgentRuntime``.

Native, provider-agnostic durability (0 new deps): wraps any ``AgentRuntime``
and persists conversation state into a B1 ``Checkpointer``
(``swarmline.protocols.checkpoint``) after each observable step boundary.
Three LangGraph-parity modes — see ``DurabilityConfig`` / ``DurabilityMode``.

This is a *transparent* decorator: every event from the inner runtime is
yielded through unchanged; checkpointing is a side effect only. Auto-resume
(Stage C1.2) restores state from the last checkpoint on ``thread_id`` before
invoking the inner runtime, when ``config.resume`` (default ``True``): a
``done`` checkpoint layers a fresh turn on top of the restored transcript
(continue the conversation); a ``running`` checkpoint (crash mid-step)
replaces the incoming messages with the restored transcript, so the model
does not re-issue already-finished tool calls.

Honest limitation (plan Risk table + Decision Point C-DP2): the thin runtime
surfaces the full transcript (``new_messages``) only at the ``final`` event,
so progress checkpoints (``tool_call_finished``) do not carry the model's
assistant text yet — they carry the incoming transcript plus an append-only
list of finished-tool pseudo-messages, so a future resume (C1.2) can see
"what work is already done" and avoid re-issuing already-finished tool calls.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from swarmline.domain_types import (
    ContentBlock,
    ImageBlock,
    Message,
    RuntimeEvent,
    TextBlock,
    ToolSpec,
)
from swarmline.durable.config import DurabilityConfig
from swarmline.protocols import Checkpointer
from swarmline.protocols.runtime import AgentRuntime

if TYPE_CHECKING:
    from swarmline.runtime.types import RuntimeConfig

logger = logging.getLogger(__name__)


def _deserialize_content_block(raw: Any) -> ContentBlock:
    """Rebuild one ``ContentBlock`` from its ``to_dict()`` payload.

    Unlike ``Message.from_memory_message`` (which silently skips a malformed
    block -- best-effort compat with an external memory source), a
    checkpoint is OUR OWN durable state: an unknown ``type`` or malformed
    fields there means corruption, so this fails LOUD with the offending
    payload rather than silently dropping it.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            "Malformed checkpoint state: content block must be a dict, got "
            f"{type(raw).__name__!r} -- {raw!r}"
        )
    block_type = raw.get("type")
    if block_type == "text":
        text = raw.get("text")
        if not isinstance(text, str):
            raise ValueError(
                f"Malformed checkpoint state: text block missing 'text' -- {raw!r}"
            )
        return TextBlock(text=text)
    if block_type == "image":
        data = raw.get("data")
        media_type = raw.get("media_type")
        if not isinstance(data, str) or not isinstance(media_type, str):
            raise ValueError(
                "Malformed checkpoint state: image block missing 'data'/"
                f"'media_type' -- {raw!r}"
            )
        return ImageBlock(data=data, media_type=media_type)
    raise ValueError(
        f"Malformed checkpoint state: unknown content block type {block_type!r} -- {raw!r}"
    )


def _deserialize_messages(payloads: Any) -> list[Message]:
    """Rebuild ``Message`` objects from a checkpoint's ``state["messages"]``.

    Mirrors ``snapshot_store.deserialize_state`` (``Message(**payload)``), but
    is a REAL decoder for ``content_blocks``: a C1.1 checkpoint can legitimately
    persist a multimodal ``Message`` (``to_dict()`` serializes each block via
    ``block.to_dict()``), and the restored transcript is re-serialized on the
    next checkpoint write (progress-checkpoint seeding) -- ``dict`` blocks left
    unparsed would blow up on that second ``.to_dict()`` call. Fails LOUD on a
    malformed payload (never silently drops history) -- a non-list payload, a
    non-dict entry, an entry that doesn't match ``Message``'s fields, or a
    malformed/unknown content block all raise ``ValueError`` with context.
    """
    if not isinstance(payloads, list):
        raise ValueError(
            "Malformed checkpoint state: 'messages' must be a list, got "
            f"{type(payloads).__name__!r}"
        )
    messages: list[Message] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            raise ValueError(
                "Malformed checkpoint state: message payload must be a dict, "
                f"got {type(payload).__name__!r} -- {payload!r}"
            )
        kwargs = dict(payload)
        raw_blocks = kwargs.get("content_blocks")
        if raw_blocks is not None:
            if not isinstance(raw_blocks, list):
                raise ValueError(
                    "Malformed checkpoint state: 'content_blocks' must be a "
                    f"list, got {type(raw_blocks).__name__!r}"
                )
            kwargs["content_blocks"] = [
                _deserialize_content_block(raw) for raw in raw_blocks
            ]
        try:
            messages.append(Message(**kwargs))
        except TypeError as exc:
            raise ValueError(
                f"Malformed checkpoint state: bad message payload -- {exc}"
            ) from exc
    return messages


def _tool_result_message(summary: Mapping[str, Any]) -> Message:
    """Turn a ``tool_call_finished`` event payload into a transcript entry.

    Used to build the "so-far" transcript for progress checkpoints so a
    resumed run (C1.2) sees the finished tool result already in history and
    does not re-issue it.
    """
    return Message(
        role="tool",
        content=str(summary.get("result_summary", "")),
        name=summary.get("name"),
        metadata={
            "correlation_id": summary.get("correlation_id"),
            "ok": summary.get("ok"),
        },
    )


class DurableRuntime:
    """Checkpoint-after-step decorator — implements ``AgentRuntime`` (5 methods)."""

    def __init__(
        self,
        inner: AgentRuntime,
        checkpointer: Checkpointer,
        config: DurabilityConfig,
    ) -> None:
        if not config.thread_id:
            raise ValueError(
                "DurabilityConfig.thread_id must be non-empty -- a durable "
                "run needs a checkpoint key"
            )
        self._inner = inner
        self._checkpointer = checkpointer
        self._config = config
        self._pending_tasks: set[asyncio.Task[None]] = set()

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        resolved_messages = messages
        # `base_parent_id` seeds the lineage: None for a fresh thread, or the
        # resumed checkpoint's id so new checkpoints written in this run
        # chain onto the restored history (time-travel lineage, C1.3).
        base_parent_id: str | None = None
        if self._config.resume:
            checkpoint = await self._checkpointer.get(self._config.thread_id)
            if checkpoint is not None:
                restored = _deserialize_messages(checkpoint.state.get("messages"))
                if checkpoint.state.get("status") == "running":
                    # Crash resume: replay from the last completed step --
                    # finished tool results are already in the transcript,
                    # so the model must not re-issue them.
                    resolved_messages = restored
                else:
                    # Fresh turn layered on a completed conversation
                    # (C-DP3 default: continue).
                    resolved_messages = [*restored, *messages]
                base_parent_id = checkpoint.id

        transcript: list[dict[str, Any]] = [m.to_dict() for m in resolved_messages]
        tool_summaries: list[dict[str, Any]] = []
        # Per-run bookkeeping of which progress checkpoints ACTUALLY landed
        # (keyed by step, populated only on a successful put -- background
        # failures never populate this). `parent_id` below is the naive
        # sequential chain (used as the next progress checkpoint's parent);
        # the terminal `final` checkpoint instead parents off the *last
        # successfully persisted* entry (see the `final` branch) so it can
        # never dangle off a failed/still-pending background write.
        persisted_steps: dict[int, str] = {}
        parent_id: str | None = base_parent_id
        step = 0

        try:
            async for event in self._inner.run(
                messages=resolved_messages,
                system_prompt=system_prompt,
                active_tools=active_tools,
                config=config,
                mode_hint=mode_hint,
            ):
                if (
                    event.type == "tool_call_finished"
                    and self._config.mode != "exit"
                    and self._config.checkpoint_on_tool
                ):
                    step += 1
                    summary = dict(event.data)
                    tool_summaries.append(summary)
                    transcript.append(_tool_result_message(summary).to_dict())
                    state = {
                        "messages": list(transcript),
                        "step": step,
                        "status": "running",
                        "events": list(tool_summaries),
                    }
                    checkpoint_id = uuid4().hex
                    if self._config.mode == "sync":
                        await self._put(state, parent_id, checkpoint_id=checkpoint_id)
                        persisted_steps[step] = checkpoint_id
                    else:
                        self._schedule_put(
                            state, parent_id, checkpoint_id, step, persisted_steps
                        )
                    parent_id = checkpoint_id
                    yield event
                    continue

                if event.type == "final":
                    # Drain pending background progress checkpoints FIRST --
                    # otherwise a slower background put can land after the
                    # terminal write (crash-resume would then misread a
                    # completed run as still "running"), and a failed put
                    # would leave the terminal checkpoint's parent dangling.
                    # No-op in exit/sync modes (nothing ever pending there).
                    await self._drain_pending()
                    last_persisted = (
                        persisted_steps[max(persisted_steps)]
                        if persisted_steps
                        else base_parent_id
                    )
                    new_messages = event.data.get("new_messages") or []
                    final_state = {"messages": list(new_messages), "status": "done"}
                    await self._put(final_state, last_persisted)
                    yield event
                    continue

                yield event
        except Exception:
            await self._drain_pending()
            raise

    async def _put(
        self,
        state: dict[str, Any],
        parent_id: str | None,
        *,
        checkpoint_id: str | None = None,
    ) -> str:
        return await self._checkpointer.put(
            self._config.thread_id,
            state,
            resource_id=self._config.resource_id,
            parent_id=parent_id,
            checkpoint_id=checkpoint_id,
        )

    def _schedule_put(
        self,
        state: dict[str, Any],
        parent_id: str | None,
        checkpoint_id: str,
        step: int,
        persisted_steps: dict[int, str],
    ) -> None:
        async def _background() -> None:
            try:
                await self._put(state, parent_id, checkpoint_id=checkpoint_id)
            except Exception:
                logger.exception(
                    "durable_runtime.background_checkpoint_failed",
                    extra={
                        "thread_id": self._config.thread_id,
                        "checkpoint_id": checkpoint_id,
                    },
                )
            else:
                persisted_steps[step] = checkpoint_id

        task = asyncio.create_task(_background())
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _drain_pending(self) -> None:
        if not self._pending_tasks:
            return
        pending = list(self._pending_tasks)
        await asyncio.gather(*pending, return_exceptions=True)

    async def cleanup(self) -> None:
        await self._drain_pending()
        await self._inner.cleanup()

    def cancel(self) -> None:
        self._inner.cancel()

    async def __aenter__(self) -> DurableRuntime:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._inner.__aexit__(*args)
