"""Unit: native thread/checkpointer/resume helpers for DeepAgents."""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph", reason="langgraph не установлен")

from swarmline.runtime.deepagents_memory import (
    build_native_invocation,
    build_native_state_notice,
    validate_native_state_config,
)
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command


def test_validate_resume_requires_checkpointer() -> None:
    """resume without checkpointer should fail-fast."""
    error = validate_native_state_config({"resume": {"i1": "ok"}})

    assert error is not None
    assert error.kind == "capability_unsupported"
    assert "checkpointer" in error.message


def test_build_native_invocation_uses_latest_message_with_thread_state() -> None:
    """Pri native thread state not replay'im ves Swarmline history in graph input."""
    messages = [
        HumanMessage(content="old question"),
        AIMessage(content="old answer"),
        HumanMessage(content="latest question"),
    ]

    payload, run_config, native_metadata = build_native_invocation(
        messages=messages,
        native_config={
            "checkpointer": object(),
            "thread_id": "thread-1",
        },
    )

    assert payload == {"messages": [messages[-1]]}
    assert run_config == {"configurable": {"thread_id": "thread-1"}}
    assert native_metadata["history_source"] == "native_thread"
    assert native_metadata["thread_id"] == "thread-1"
    assert native_metadata["uses_checkpointer"] is True
    assert native_metadata["resume_requested"] is False


def test_build_native_invocation_uses_command_for_resume() -> None:
    """resume prevrashchaetsya in LangGraph Command(resume=...)."""
    payload, run_config, native_metadata = build_native_invocation(
        messages=[HumanMessage(content="ignored")],
        native_config={
            "checkpointer": object(),
            "thread_id": "thread-2",
            "resume": {"interrupt-1": {"type": "approve"}},
        },
    )

    assert isinstance(payload, Command)
    assert payload.resume == {"interrupt-1": {"type": "approve"}}
    assert run_config == {"configurable": {"thread_id": "thread-2"}}
    assert native_metadata["resume_requested"] is True


def test_build_native_invocation_replays_full_history_when_only_store_is_configured() -> (
    None
):
    """Store without checkpointer not should vklyuchat latest-message-only semantics."""
    messages = [
        HumanMessage(content="old question"),
        AIMessage(content="old answer"),
        HumanMessage(content="latest question"),
    ]

    payload, run_config, native_metadata = build_native_invocation(
        messages=messages,
        native_config={
            "store": object(),
            "thread_id": "thread-3",
        },
    )

    assert payload == {"messages": messages}
    assert run_config == {"configurable": {"thread_id": "thread-3"}}
    assert native_metadata["history_source"] == "swarmline_history"
    assert native_metadata["uses_store"] is True
    assert native_metadata["uses_checkpointer"] is False


def test_build_native_state_notice_marks_semantic_difference() -> None:
    """Pri native thread/checkpointer semantics vydaem yavnyy notice."""
    notice = build_native_state_notice(
        {
            "history_source": "native_thread",
            "thread_id": "thread-1",
            "resume_requested": False,
        }
    )

    assert notice is not None
    assert "native thread" in notice
    assert "thread-1" in notice
