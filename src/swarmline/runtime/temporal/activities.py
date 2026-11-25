"""Temporal activities — the non-deterministic half of the agent loop.

``AgentActivities`` is instantiated once per worker with worker-owned
dependencies (LLM call, ToolExecutor, optional event publisher) and its
bound methods are registered as activities. All IO lives here; the workflow
only orchestrates.

Reuses the thin runtime's pure pieces: ``build_react_prompt`` (tool
instructions) and ``parse_envelope`` (model-output parsing), so the model
contract is identical to ``runtime="thin"``.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Awaitable, Callable
from typing import Any

from temporalio import activity

from swarmline.runtime.temporal.payloads import (
    EventDict,
    HistoryAppendInput,
    HistoryAppendOutput,
    LlmStepInput,
    LlmStepOutput,
    ToolStepInput,
    ToolStepOutput,
    message_from_dict,
    message_to_dict,
)
from swarmline.runtime.temporal.state import HistoryStore
from swarmline.runtime.temporal.stream import RunEventPublisher
from swarmline.runtime.thin.parsers import extract_text_fallback, parse_envelope
from swarmline.runtime.thin.prompts import build_react_prompt
from swarmline.runtime.types import RuntimeConfig, ToolSpec

# llm_call(messages, system_prompt, model) -> raw model text
LlmCallFn = Callable[[list[dict[str, str]], str, str], Awaitable[Any]]

_RESULT_SUMMARY_CHARS = 200


async def _drain_llm_result(result: Any) -> str:
    """Normalize default_llm_call output (str | LlmCallResult | stream) to text."""
    if isinstance(result, str):
        return result
    if hasattr(result, "__aiter__"):
        chunks: list[str] = []
        async for chunk in result:
            chunks.append(str(chunk))
        return "".join(chunks)
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text
    return str(result)


def _make_default_llm_call(base_config: RuntimeConfig) -> LlmCallFn:
    """Default LLM path: thin's provider-resolving client, buffered."""

    async def _call(
        messages: list[dict[str, str]], system_prompt: str, model: str
    ) -> str:
        from swarmline.runtime.thin.llm_client import default_llm_call

        config = dataclasses.replace(base_config, model=model) if model else base_config
        result = await default_llm_call(config, messages, system_prompt)
        return await _drain_llm_result(result)

    return _call


class AgentActivities:
    """Worker-side activity implementations for ``AgentLoopWorkflow``.

    Parameters
    ----------
    tool_executor:
        A ``ToolExecutor`` (thin runtime) owning the worker's local tools and
        MCP servers. Tool failures come back as JSON error strings, never
        exceptions — the loop shows them to the model.
    llm_call:
        Optional ``(messages, system_prompt, model) -> text`` override.
        Default: thin's ``default_llm_call`` with provider resolution from
        ``base_config`` (api_key/base_url) and the per-run model.
    base_config:
        RuntimeConfig template for the default LLM path (credentials,
        base_url, request options). The per-run model overrides its model.
    publisher:
        Optional ``RunEventPublisher``; when set and the run has
        ``stream_events=True``, activities publish their events live.
    approval_policy:
        Optional ``ApprovalPolicy`` (``hitl/policies.py``). When it requires
        approval for a tool call, ``tool_step`` returns a
        ``needs_approval=True`` marker without executing; the workflow then
        waits durably for an approval signal and re-dispatches with
        ``approved=True``, which skips this check.
    history_store:
        Optional ``HistoryStore`` (``state.py``) backing reference-based
        history. Required when clients run with
        ``use_reference_history=True``; must be shared by every worker on
        the task queue (Postgres/SQLite via ``MessageStoreHistoryAdapter``).
    compaction_config:
        Optional ``CompactionConfig`` (``swarmline.compaction``). Applied
        when materializing referenced history for an LLM step: over the
        token threshold, old tool pairs collapse and oldest messages drop
        (tiers 1 + 3). The store itself is never rewritten.
    """

    def __init__(
        self,
        *,
        tool_executor: Any,
        llm_call: LlmCallFn | None = None,
        base_config: RuntimeConfig | None = None,
        publisher: RunEventPublisher | None = None,
        approval_policy: Any = None,
        history_store: HistoryStore | None = None,
        compaction_config: Any = None,
    ) -> None:
        self._executor = tool_executor
        self._base_config = base_config or RuntimeConfig(runtime_name="temporal")
        self._llm_call = llm_call or _make_default_llm_call(self._base_config)
        self._publisher = publisher
        self._approval_policy = approval_policy
        self._history = history_store
        self._compaction_config = compaction_config

    async def _publish(self, inp: Any, events: list[EventDict]) -> None:
        if self._publisher is None or not inp.stream_events or not events:
            return
        try:
            await self._publisher.publish(inp.run_id, events)
        except Exception:  # noqa: BLE001 — streaming is best-effort
            pass

    def _require_history(self) -> HistoryStore:
        if self._history is None:
            from temporalio.exceptions import ApplicationError

            raise ApplicationError(
                "Run uses reference-based history but this worker has no "
                "history_store configured — pass one to AgentActivities/"
                "build_worker (swarmline.runtime.temporal.state).",
                non_retryable=True,
            )
        return self._history

    async def _materialize_messages(
        self, inp: LlmStepInput, system_prompt: str
    ) -> list[dict[str, Any]]:
        """The conversation for this step: inline, or loaded from the
        history store (reference mode), with optional compaction."""
        if inp.history_revision < 0:
            return inp.messages
        messages = await self._require_history().load(inp.run_id)
        if self._compaction_config is None:
            return messages

        from swarmline.compaction import ConversationCompactionFilter

        compactor = ConversationCompactionFilter(config=self._compaction_config)
        compacted, _ = await compactor.filter(
            [message_from_dict(m) for m in messages], system_prompt
        )
        return [message_to_dict(m) for m in compacted]

    @activity.defn(name="swarmline_llm_step")
    async def llm_step(self, inp: LlmStepInput) -> LlmStepOutput:
        """One model call: build prompt, call LLM, parse the envelope.

        Transient provider failures propagate as exceptions so Temporal's
        retry policy handles them; only *parse-level* failures return
        ``kind="error"``.
        """
        tools = [
            ToolSpec(
                name=t["name"],
                description=t.get("description", ""),
                parameters=t.get("parameters", {}),
                is_local=t.get("is_local", False),
            )
            for t in inp.tools
        ]
        prompt = (
            build_react_prompt(inp.system_prompt, tools) if tools else inp.system_prompt
        )
        messages = await self._materialize_messages(inp, prompt)
        raw = await _drain_llm_result(await self._llm_call(messages, prompt, inp.model))

        out = self._parse_llm_output(inp, raw, has_tools=bool(tools))
        await self._publish(inp, out.events)
        return out

    def _parse_llm_output(
        self, inp: LlmStepInput, raw: str, *, has_tools: bool
    ) -> LlmStepOutput:
        def _event(index: int, event_type: str, data: dict[str, Any]) -> EventDict:
            return {
                "id": f"{inp.run_id}:{inp.iteration}:llm:{index}",
                "type": event_type,
                "data": data,
            }

        if not has_tools:
            text = raw.strip()
            return LlmStepOutput(
                kind="final",
                text=text,
                raw=raw,
                events=[_event(0, "assistant_delta", {"text": text})],
            )

        envelope = parse_envelope(raw)
        if envelope is None:
            fallback = extract_text_fallback(raw)
            if fallback:
                return LlmStepOutput(
                    kind="final",
                    text=fallback,
                    raw=raw,
                    events=[_event(0, "assistant_delta", {"text": fallback})],
                )
            return LlmStepOutput(
                kind="error",
                raw=raw,
                error_kind="bad_model_output",
                error_message="Model returned neither a valid envelope nor text",
            )

        if envelope.type == "final":
            text = envelope.final_message or ""
            return LlmStepOutput(
                kind="final",
                text=text,
                raw=raw,
                events=[_event(0, "assistant_delta", {"text": text})],
            )

        if envelope.type == "clarify":
            questions = "\n".join(f"- {q.text}" for q in envelope.questions)
            text = (
                f"{envelope.assistant_message}\n{questions}".strip()
                if envelope.assistant_message
                else questions
            )
            return LlmStepOutput(
                kind="final",
                text=text,
                raw=raw,
                events=[_event(0, "assistant_delta", {"text": text})],
            )

        tool = envelope.get_tool_call()
        correlation_id = tool.correlation_id or f"{inp.run_id}:{inp.iteration}"
        events: list[EventDict] = []
        if envelope.assistant_message:
            events.append(
                _event(0, "assistant_delta", {"text": envelope.assistant_message})
            )
        return LlmStepOutput(
            kind="tool_call",
            raw=raw,
            assistant_message=envelope.assistant_message,
            tool_name=tool.name,
            tool_args=tool.args,
            correlation_id=correlation_id,
            events=events,
        )

    def _requires_approval(self, inp: ToolStepInput) -> bool:
        if self._approval_policy is None or inp.approved:
            return False
        return bool(
            self._approval_policy.requires_approval(
                "tool_call", {"tool_name": inp.name, "tool_args": inp.args}
            )
        )

    @activity.defn(name="swarmline_tool_step")
    async def tool_step(self, inp: ToolStepInput) -> ToolStepOutput:
        """One tool call through the worker's ToolExecutor (hooks + policy).

        When the approval policy gates the call, nothing executes: the
        output carries ``needs_approval=True`` plus an ``approval_requested``
        event, and the workflow takes over (durable signal wait).
        """
        if self._requires_approval(inp):
            requested_event: EventDict = {
                "id": f"{inp.run_id}:{inp.iteration}:approval:0",
                "type": "approval_requested",
                "data": {
                    "run_id": inp.run_id,
                    "name": inp.name,
                    "args": inp.args,
                    "correlation_id": inp.correlation_id,
                },
            }
            await self._publish(inp, [requested_event])
            return ToolStepOutput(
                name=inp.name,
                correlation_id=inp.correlation_id,
                ok=False,
                result="",
                needs_approval=True,
                events=[requested_event],
            )

        started_event: EventDict = {
            "id": f"{inp.run_id}:{inp.iteration}:tool:0",
            "type": "tool_call_started",
            "data": {
                "name": inp.name,
                "correlation_id": inp.correlation_id,
                "args": inp.args,
            },
        }
        await self._publish(inp, [started_event])

        result = await self._executor.execute(inp.name, inp.args)

        ok = True
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and "error" in parsed:
                ok = False
        except (json.JSONDecodeError, TypeError):
            pass

        finished_event: EventDict = {
            "id": f"{inp.run_id}:{inp.iteration}:tool:1",
            "type": "tool_call_finished",
            "data": {
                "name": inp.name,
                "correlation_id": inp.correlation_id,
                "ok": ok,
                "result_summary": result[:_RESULT_SUMMARY_CHARS],
            },
        }
        await self._publish(inp, [finished_event])

        return ToolStepOutput(
            name=inp.name,
            correlation_id=inp.correlation_id,
            ok=ok,
            result=result,
            events=[started_event, finished_event],
        )

    @activity.defn(name="swarmline_history_append")
    async def history_append(self, inp: HistoryAppendInput) -> HistoryAppendOutput:
        """Append a message delta to the run's history store.

        Idempotent under retries: the store skips appends whose
        ``expected_revision`` it has already advanced past.
        """
        revision = await self._require_history().append(
            inp.run_id, inp.messages, expected_revision=inp.expected_revision
        )
        return HistoryAppendOutput(revision=revision)
