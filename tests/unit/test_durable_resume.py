"""TDD tests for Stage C1.2 — ``DurableRuntime`` auto-resume from the last
checkpoint (crash-mid-step resume).

Uses the same scripted fake ``AgentRuntime`` + ``InMemoryCheckpointer`` as
``test_durable_runtime.py`` — zero new dependencies, zero vendor SDKs. Covers
the 6 plan-mandated tests plus edge cases (malformed checkpoint payload fails
loud; resumed-run lineage chains off the resumed checkpoint).

Fakes/helpers live in ``tests/unit/_durable_fakes.py`` (extracted for the
400-line file-size cap — ``_graph_streaming_fakes.py``/``_followup_fakes.py``
convention).
"""

from __future__ import annotations

import pytest
from _durable_fakes import ScriptedRuntime, drain, make_config

from swarmline.domain_types import ImageBlock, Message, RuntimeEvent, TextBlock
from swarmline.durable import DurableRuntime
from swarmline.session import InMemoryCheckpointer

# ---------------------------------------------------------------------------
# Plan-mandated tests (6)
# ---------------------------------------------------------------------------


async def test_resume_disabled_ignores_existing_checkpoint() -> None:
    checkpointer = InMemoryCheckpointer()
    await checkpointer.put(
        "t1", {"messages": [{"role": "user", "content": "old"}], "status": "done"}
    )
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="exit", resume=False))

    incoming = [Message(role="user", content="new")]
    await drain(runtime, messages=incoming)

    assert fake.received_messages == incoming


async def test_crash_midstep_persists_last_completed_step() -> None:
    checkpointer = InMemoryCheckpointer()
    events: list[RuntimeEvent | BaseException] = [
        RuntimeEvent.tool_call_started("a", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("a", "c1", result_summary="42"),
        RuntimeError("boom"),
    ]
    fake = ScriptedRuntime(events)
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="sync"))

    with pytest.raises(RuntimeError, match="boom"):
        await drain(runtime, messages=[Message(role="user", content="go")])

    cp = await checkpointer.get("t1")
    assert cp is not None
    assert cp.state["status"] == "running"
    assert any(m.get("name") == "a" for m in cp.state["messages"])


async def test_resume_after_crash_continues_from_last_checkpoint() -> None:
    checkpointer = InMemoryCheckpointer()
    crash_events: list[RuntimeEvent | BaseException] = [
        RuntimeEvent.tool_call_started("a", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("a", "c1", result_summary="42"),
        RuntimeError("boom"),
    ]
    run1 = DurableRuntime(
        ScriptedRuntime(crash_events), checkpointer, make_config(mode="sync")
    )
    with pytest.raises(RuntimeError, match="boom"):
        await drain(run1, messages=[Message(role="user", content="go")])

    fake2 = ScriptedRuntime([RuntimeEvent.final("done")])
    run2 = DurableRuntime(fake2, checkpointer, make_config(mode="sync"))
    await drain(
        run2, messages=[Message(role="user", content="ignored-if-crash-resume")]
    )

    assert fake2.received_messages is not None
    assert any(m.name == "a" for m in fake2.received_messages)

    cp = await checkpointer.get("t1")
    assert cp is not None
    assert cp.state["status"] == "done"


async def test_resume_does_not_recall_finished_tool() -> None:
    checkpointer = InMemoryCheckpointer()
    crash_events: list[RuntimeEvent | BaseException] = [
        RuntimeEvent.tool_call_started("search", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("search", "c1", result_summary="42 results"),
        RuntimeError("boom"),
    ]
    run1 = DurableRuntime(
        ScriptedRuntime(crash_events), checkpointer, make_config(mode="sync")
    )
    with pytest.raises(RuntimeError, match="boom"):
        await drain(run1, messages=[Message(role="user", content="go")])

    fake2 = ScriptedRuntime([RuntimeEvent.final("done")])
    run2 = DurableRuntime(fake2, checkpointer, make_config(mode="sync"))
    await drain(run2, messages=[Message(role="user", content="whatever")])

    assert fake2.received_messages is not None
    tool_messages = [
        m for m in fake2.received_messages if m.role == "tool" and m.name == "search"
    ]
    # Present exactly once (from the restored transcript) -- the resumed run
    # must NOT re-issue a finished tool call.
    assert len(tool_messages) == 1
    assert "42 results" in tool_messages[0].content


async def test_resume_after_done_continues_conversation() -> None:
    checkpointer = InMemoryCheckpointer()
    fake1 = ScriptedRuntime(
        [
            RuntimeEvent.final(
                "hi", new_messages=[Message(role="assistant", content="hello")]
            )
        ]
    )
    run1 = DurableRuntime(fake1, checkpointer, make_config(mode="exit"))
    await drain(run1, messages=[Message(role="user", content="hi")])

    fake2 = ScriptedRuntime([RuntimeEvent.final("bye")])
    run2 = DurableRuntime(fake2, checkpointer, make_config(mode="exit"))
    await drain(run2, messages=[Message(role="user", content="what's up")])

    assert fake2.received_messages == [
        Message(role="assistant", content="hello"),
        Message(role="user", content="what's up"),
    ]


async def test_resume_with_no_prior_checkpoint_is_plain_run() -> None:
    checkpointer = InMemoryCheckpointer()
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="exit"))

    incoming = [Message(role="user", content="hello")]
    await drain(runtime, messages=incoming)

    assert fake.received_messages == incoming


# ---------------------------------------------------------------------------
# Edge cases (plan "Edge cases" section, C1.2)
# ---------------------------------------------------------------------------


async def test_resume_with_malformed_checkpoint_messages_fails_loud() -> None:
    checkpointer = InMemoryCheckpointer()
    await checkpointer.put("t1", {"messages": "not-a-list", "status": "done"})
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="exit"))

    with pytest.raises(ValueError, match="messages"):
        await drain(runtime, messages=[Message(role="user", content="hi")])


async def test_resume_with_missing_messages_key_fails_loud() -> None:
    checkpointer = InMemoryCheckpointer()
    await checkpointer.put("t1", {"status": "done"})  # no "messages" key at all
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="exit"))

    with pytest.raises(ValueError, match="messages"):
        await drain(runtime, messages=[Message(role="user", content="hi")])


async def test_resumed_run_new_checkpoint_parents_off_resumed_checkpoint() -> None:
    checkpointer = InMemoryCheckpointer()
    cp_id = await checkpointer.put("t1", {"messages": [], "status": "done"})

    fake = ScriptedRuntime(
        [
            RuntimeEvent.tool_call_started("a", args={}, correlation_id="c1"),
            RuntimeEvent.tool_call_finished("a", "c1"),
            RuntimeEvent.final("done"),
        ]
    )
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="sync"))
    await drain(runtime, messages=[Message(role="user", content="go")])

    history = await checkpointer.list("t1")
    new_entries = [m for m in history if m.id != cp_id]
    assert new_entries
    assert new_entries[0].parent_id == cp_id


# ---------------------------------------------------------------------------
# Fix-cycle r1 — content_blocks round-trip (GPT-5.5 review MAJOR)
# ---------------------------------------------------------------------------


async def test_resume_round_trips_content_blocks() -> None:
    """A C1.1 checkpoint can legitimately persist a multimodal ``Message``
    (``to_dict()`` serializes ``content_blocks`` via ``block.to_dict()``).
    On resume, the restored transcript must carry REAL block objects, not
    raw dicts -- otherwise the very next ``m.to_dict()`` call (seeding the
    next checkpoint's transcript) raises ``AttributeError``."""
    checkpointer = InMemoryCheckpointer()
    multimodal = Message(
        role="user",
        content="look at this",
        content_blocks=[
            TextBlock(text="a caption"),
            ImageBlock(data="YmFzZTY0", media_type="image/png"),
        ],
    )
    crash_events: list[RuntimeEvent | BaseException] = [
        RuntimeEvent.tool_call_started("a", args={}, correlation_id="c1"),
        RuntimeEvent.tool_call_finished("a", "c1"),
        RuntimeError("boom"),
    ]
    run1 = DurableRuntime(
        ScriptedRuntime(crash_events), checkpointer, make_config(mode="sync")
    )
    with pytest.raises(RuntimeError, match="boom"):
        await drain(run1, messages=[multimodal])

    cp = await checkpointer.get("t1")
    assert cp is not None
    # C1.1 really does persist the block as a raw dict (Message.to_dict()).
    stored_blocks = cp.state["messages"][0]["content_blocks"]
    assert all(isinstance(b, dict) for b in stored_blocks)

    fake2 = ScriptedRuntime([RuntimeEvent.final("done")])
    run2 = DurableRuntime(fake2, checkpointer, make_config(mode="sync"))
    # Must NOT raise AttributeError: 'dict' object has no attribute 'to_dict'
    # (the restored transcript is re-serialized via .to_dict() when seeding
    # this run's own "messages so far").
    await drain(run2, messages=[Message(role="user", content="continue")])

    assert fake2.received_messages is not None
    restored = fake2.received_messages[0]
    assert restored.content_blocks is not None
    assert isinstance(restored.content_blocks[0], TextBlock)
    assert restored.content_blocks[0].text == "a caption"
    assert isinstance(restored.content_blocks[1], ImageBlock)
    assert restored.content_blocks[1].data == "YmFzZTY0"
    assert restored.content_blocks[1].media_type == "image/png"


async def test_resume_with_unknown_content_block_type_fails_loud() -> None:
    checkpointer = InMemoryCheckpointer()
    await checkpointer.put(
        "t1",
        {
            "messages": [
                {
                    "role": "user",
                    "content": "x",
                    "content_blocks": [{"type": "video", "data": "..."}],
                }
            ],
            "status": "done",
        },
    )
    fake = ScriptedRuntime([RuntimeEvent.final("hi")])
    runtime = DurableRuntime(fake, checkpointer, make_config(mode="exit"))

    with pytest.raises(ValueError, match="video"):
        await drain(runtime, messages=[Message(role="user", content="hi")])
