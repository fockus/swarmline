"""Workflow/activity payload dataclasses for the Temporal runtime.

These cross the wire as Temporal payloads (JSON data converter), so they are
plain dataclasses of JSON-safe values. Messages travel as dicts
(``role``/``content``/``name``/``tool_calls``/``metadata``); events as
``{"id": ..., "type": ..., "data": {...}}`` — reconstructable into
``RuntimeEvent`` on the client.

Note: ``content_blocks`` (multimodal) are not carried in v1 — see the
proposal's payload-strategy section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from swarmline.domain_types import Message

EventDict = dict[str, Any]

# Wire-contract names shared by workflow, worker, and client facade.
WORKFLOW_NAME = "SwarmlineAgentLoop"
LLM_ACTIVITY = "swarmline_llm_step"
TOOL_ACTIVITY = "swarmline_tool_step"
HISTORY_ACTIVITY = "swarmline_history_append"
APPROVAL_SIGNAL = "swarmline_approval"
PENDING_APPROVALS_QUERY = "swarmline_pending_approvals"


def message_to_dict(message: Message) -> dict[str, Any]:
    """Serialize a Message for workflow transport (content_blocks dropped)."""
    data: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.name is not None:
        data["name"] = message.name
    if message.tool_calls is not None:
        data["tool_calls"] = message.tool_calls
    if message.metadata is not None:
        data["metadata"] = message.metadata
    return data


def message_from_dict(data: dict[str, Any]) -> Message:
    """Deserialize a Message from workflow transport."""
    return Message(
        role=data.get("role", ""),
        content=data.get("content", ""),
        name=data.get("name"),
        tool_calls=data.get("tool_calls"),
        metadata=data.get("metadata"),
    )


@dataclass
class AgentRunInput:
    """Input of ``AgentLoopWorkflow`` — one agent run.

    Reference-based history (``use_reference_history=True``): the growing
    conversation lives in the worker's ``HistoryStore``; LLM step inputs
    carry a revision number instead of the full message list, and the loop
    appends per-turn deltas via the history activity. Long runs roll over
    workflow history via continue-as-new (``continue_after_iterations``),
    carrying only the fields below — ``history_revision``,
    ``start_iteration``, ``tool_calls_used``, and the accumulated
    ``carried_*`` outputs.
    """

    messages: list[dict[str, Any]]
    system_prompt: str
    tools: list[dict[str, Any]]
    run_id: str
    model: str
    max_iterations: int = 6
    max_tool_calls: int = 8
    stream_events: bool = False
    llm_timeout_seconds: float = 300.0
    tool_timeout_seconds: float = 120.0
    llm_retry_attempts: int = 3
    tool_retry_attempts: int = 1
    approval_timeout_seconds: float = 86400.0
    use_reference_history: bool = False
    continue_after_iterations: int = 0
    history_revision: int = -1
    start_iteration: int = 0
    tool_calls_used: int = 0
    carried_new_messages: list[dict[str, Any]] = field(default_factory=list)
    carried_events: list[EventDict] = field(default_factory=list)


@dataclass
class LlmStepInput:
    """Input of the LLM activity — one model call of the loop.

    ``history_revision >= 0`` marks reference mode: ``messages`` is empty
    and the activity materializes the conversation from the worker's
    ``HistoryStore`` (applying compaction when configured).
    """

    run_id: str
    iteration: int
    messages: list[dict[str, Any]]
    system_prompt: str
    tools: list[dict[str, Any]]
    model: str
    stream_events: bool = False
    history_revision: int = -1


@dataclass
class LlmStepOutput:
    """Parsed result of one model call.

    ``kind``: ``"final"`` (loop ends), ``"tool_call"`` (dispatch a tool), or
    ``"error"`` (unrecoverable model output).
    """

    kind: str
    text: str = ""
    raw: str = ""
    assistant_message: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    error_kind: str = ""
    error_message: str = ""
    events: list[EventDict] = field(default_factory=list)


@dataclass
class ToolStepInput:
    """Input of the tool activity — one tool call.

    ``approved=True`` marks a re-dispatch after a human approval signal:
    the activity skips its approval-policy check and executes.
    """

    run_id: str
    iteration: int
    name: str
    args: dict[str, Any]
    correlation_id: str
    stream_events: bool = False
    approved: bool = False


@dataclass
class ToolStepOutput:
    """Result of one tool call. Tool failures land in ``result`` as JSON
    errors (``ok=False``) so the model can react — they do not fail the run.

    ``needs_approval=True`` means the worker's approval policy gated the
    call: the tool did NOT execute and the workflow must wait for an
    :class:`ApprovalDecision` signal before re-dispatching.
    """

    name: str
    correlation_id: str
    ok: bool
    result: str
    needs_approval: bool = False
    events: list[EventDict] = field(default_factory=list)


@dataclass
class ApprovalDecision:
    """Human decision on a pending tool call — the approval signal payload.

    ``modifications`` (optional) are merged over the tool args before the
    approved call executes, mirroring ``ApprovalResponse.modifications``.
    """

    correlation_id: str
    approved: bool
    reason: str = ""
    modifications: dict[str, Any] = field(default_factory=dict)


@dataclass
class HistoryAppendInput:
    """Input of the history activity — append a message delta to the store.

    ``expected_revision`` makes the append idempotent under activity
    retries: a store whose revision already advanced past it treats the
    call as a duplicate and returns the current revision unchanged.
    """

    run_id: str
    messages: list[dict[str, Any]]
    expected_revision: int = -1


@dataclass
class HistoryAppendOutput:
    """Result of the history activity — the store revision after append."""

    revision: int


@dataclass
class AgentRunResult:
    """Output of ``AgentLoopWorkflow``.

    ``status="continue"`` is internal: the loop hit its
    continue-as-new boundary and the workflow rolls over — clients never
    see it.
    """

    text: str
    new_messages: list[dict[str, Any]]
    events: list[EventDict]
    iterations: int
    tool_calls: int
    status: str = "ok"  # "ok" | "error" | "continue" (internal)
    error_kind: str = ""
    error_message: str = ""
    history_revision: int = -1
