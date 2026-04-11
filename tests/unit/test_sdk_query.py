"""Tests for sdk_query - one-shot query wrapper."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("claude_agent_sdk", reason="claude-agent-sdk не установлен")

pytestmark = pytest.mark.requires_claude_sdk

from swarmline.runtime.sdk_query import one_shot_query, stream_one_shot_query  # noqa: E402


def _make_sdk_text_block(text: str = "Ответ") -> MagicMock:
    from claude_agent_sdk import TextBlock

    block = MagicMock(spec=TextBlock)
    block.text = text
    return block


def _make_sdk_assistant_msg(blocks: list) -> MagicMock:
    from claude_agent_sdk import AssistantMessage

    msg = MagicMock(spec=AssistantMessage)
    msg.content = blocks
    msg.model = "sonnet"
    msg.parent_tool_use_id = None
    msg.error = None
    return msg


def _make_sdk_result_msg(
    session_id: str = "sess-1",
    cost: float = 0.01,
    structured_output: Any = None,
) -> MagicMock:
    from claude_agent_sdk import ResultMessage

    msg = MagicMock(spec=ResultMessage)
    msg.session_id = session_id
    msg.total_cost_usd = cost
    msg.usage = {"input_tokens": 10, "output_tokens": 5}
    msg.structured_output = structured_output
    msg.duration_ms = 500
    msg.duration_api_ms = 400
    msg.num_turns = 1
    msg.is_error = False
    msg.result = None
    msg.subtype = "success"
    return msg


def _make_sdk_stream_event(event: dict[str, Any]) -> MagicMock:
    from claude_agent_sdk.types import StreamEvent

    msg = MagicMock(spec=StreamEvent)
    msg.uuid = "ev-1"
    msg.session_id = "sess-1"
    msg.event = event
    msg.parent_tool_use_id = None
    return msg


def _make_sdk_task_started_msg(description: str = "Research task") -> MagicMock:
    from claude_agent_sdk import SystemMessage

    msg = MagicMock(spec=SystemMessage)
    msg.description = description
    msg.session_id = "sess-1"
    msg.subtype = "task_started"
    msg.data = {"description": description}
    return msg


def _make_sdk_task_progress_msg(
    description: str = "Working",
    last_tool_name: str | None = None,
) -> MagicMock:
    from claude_agent_sdk import SystemMessage

    msg = MagicMock(spec=SystemMessage)
    msg.description = description
    msg.last_tool_name = last_tool_name
    msg.session_id = "sess-1"
    msg.subtype = "task_progress"
    msg.data = {"description": description, "last_tool_name": last_tool_name}
    return msg


def _make_sdk_task_notification_msg(
    summary: str = "Task complete",
    status: str = "completed",
) -> MagicMock:
    from claude_agent_sdk import SystemMessage

    msg = MagicMock(spec=SystemMessage)
    msg.summary = summary
    msg.status = status
    msg.session_id = "sess-1"
    msg.subtype = "task_notification"
    msg.data = {"summary": summary, "status": status}
    return msg


def _make_sdk_tool_use_block(
    name: str = "calc",
    input_data: dict[str, Any] | None = None,
) -> MagicMock:
    from claude_agent_sdk import ToolUseBlock

    block = MagicMock(spec=ToolUseBlock)
    block.name = name
    block.input = input_data or {"expr": "2+2"}
    return block


def _make_sdk_tool_result_block(content: Any = "4") -> MagicMock:
    from claude_agent_sdk import ToolResultBlock

    block = MagicMock(spec=ToolResultBlock)
    block.content = content
    return block


class TestOneShotQuery:
    """one_shot_query - obertka nad SDK query() with swarmline tipami."""

    @pytest.mark.asyncio
    async def test_basic_query_returns_text(self) -> None:
        """Basic query returns tekstovyy response."""

        async def fake_query(**kwargs):
            yield _make_sdk_assistant_msg([_make_sdk_text_block("42")])
            yield _make_sdk_result_msg()

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            result = await one_shot_query("What is 6*7?")

        assert result.text == "42"

    @pytest.mark.asyncio
    async def test_query_returns_session_id(self) -> None:
        """Result contains session_id."""

        async def fake_query(**kwargs):
            yield _make_sdk_assistant_msg([_make_sdk_text_block("ok")])
            yield _make_sdk_result_msg(session_id="sess-xyz")

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            result = await one_shot_query("test")

        assert result.session_id == "sess-xyz"

    @pytest.mark.asyncio
    async def test_query_returns_cost(self) -> None:
        """Result contains total_cost_usd."""

        async def fake_query(**kwargs):
            yield _make_sdk_assistant_msg([_make_sdk_text_block("ok")])
            yield _make_sdk_result_msg(cost=0.05)

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            result = await one_shot_query("test")

        assert result.total_cost_usd == 0.05

    @pytest.mark.asyncio
    async def test_query_returns_structured_output(self) -> None:
        """Result contains structured_output."""
        struct = {"answer": "42"}

        async def fake_query(**kwargs):
            yield _make_sdk_assistant_msg([_make_sdk_text_block("42")])
            yield _make_sdk_result_msg(structured_output=struct)

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            result = await one_shot_query("test")

        assert result.structured_output == struct

    @pytest.mark.asyncio
    async def test_query_with_system_prompt(self) -> None:
        """system_prompt peredaetsya in SDK."""
        captured_options = {}

        async def fake_query(**kwargs):
            captured_options.update(kwargs)
            yield _make_sdk_assistant_msg([_make_sdk_text_block("ok")])
            yield _make_sdk_result_msg()

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            await one_shot_query("test", system_prompt="Be concise")

        assert captured_options["options"].system_prompt == "Be concise"

    @pytest.mark.asyncio
    async def test_query_with_model(self) -> None:
        """model peredaetsya in SDK."""
        captured_options = {}

        async def fake_query(**kwargs):
            captured_options.update(kwargs)
            yield _make_sdk_assistant_msg([_make_sdk_text_block("ok")])
            yield _make_sdk_result_msg()

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            await one_shot_query("test", model="opus")

        assert captured_options["options"].model == "opus"

    @pytest.mark.asyncio
    async def test_query_with_hooks(self) -> None:
        """hooks are passed in SDK options."""
        captured_options = {}
        hooks = {"PreToolUse": []}

        async def fake_query(**kwargs):
            captured_options.update(kwargs)
            yield _make_sdk_assistant_msg([_make_sdk_text_block("ok")])
            yield _make_sdk_result_msg()

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            await one_shot_query("test", hooks=hooks)

        assert captured_options["options"].hooks == hooks

    @pytest.mark.asyncio
    async def test_query_with_extended_sdk_options(self) -> None:
        """budget/fallback/betas/env/setting_sources are passed in SDK."""
        captured_options = {}

        async def fake_query(**kwargs):
            captured_options.update(kwargs)
            yield _make_sdk_assistant_msg([_make_sdk_text_block("ok")])
            yield _make_sdk_result_msg()

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            await one_shot_query(
                "test",
                max_budget_usd=5.0,
                fallback_model="haiku",
                betas=["context-1m-2025-08-07"],
                env={"MY_VAR": "value"},
                setting_sources=["project", "user"],
            )

        options = captured_options["options"]
        assert options.max_budget_usd == 5.0
        assert options.fallback_model == "haiku"
        assert options.betas == ["context-1m-2025-08-07"]
        assert options.env == {"MY_VAR": "value"}
        assert options.setting_sources == ["project", "user"]

    @pytest.mark.asyncio
    async def test_no_result_message_raises_runtime_error(self) -> None:
        """If nott ResultMessage - one_shot_query not schitaet eto success."""

        async def fake_query(**kwargs):
            yield _make_sdk_assistant_msg([_make_sdk_text_block("partial")])

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            with pytest.raises(RuntimeError, match="final ResultMessage"):
                await one_shot_query("test")


class TestStreamOneShotQuery:
    """stream_one_shot_query — true streaming wrapper for one-shot SDK path."""

    @pytest.mark.asyncio
    async def test_stream_yields_text_deltas_and_done(self) -> None:
        async def fake_query(**kwargs):
            yield _make_sdk_assistant_msg([_make_sdk_text_block("Hello ")])
            yield _make_sdk_assistant_msg([_make_sdk_text_block("World")])
            yield _make_sdk_result_msg(session_id="sess-xyz", cost=0.5)

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            events = []
            async for event in stream_one_shot_query("hi"):
                events.append(event)

        assert [event.type for event in events] == ["text_delta", "text_delta", "done"]
        assert events[0].text == "Hello "
        assert events[1].text == "World"
        assert events[2].text == "Hello World"
        assert events[2].session_id == "sess-xyz"
        assert events[2].total_cost_usd == 0.5

    @pytest.mark.asyncio
    async def test_stream_done_contains_structured_output(self) -> None:
        async def fake_query(**kwargs):
            yield _make_sdk_assistant_msg([_make_sdk_text_block("42")])
            yield _make_sdk_result_msg(structured_output={"answer": 42})

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            events = []
            async for event in stream_one_shot_query("test"):
                events.append(event)

        assert events[-1].type == "done"
        assert events[-1].structured_output == {"answer": 42}

    @pytest.mark.asyncio
    async def test_stream_ignores_partial_stream_events_by_default(self) -> None:
        async def fake_query(**kwargs):
            yield _make_sdk_stream_event(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "partial"},
                }
            )
            yield _make_sdk_assistant_msg([_make_sdk_text_block("final")])
            yield _make_sdk_result_msg()

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            events = []
            async for event in stream_one_shot_query("test"):
                events.append(event)

        assert [event.type for event in events] == ["text_delta", "done"]
        assert events[0].text == "final"

    @pytest.mark.asyncio
    async def test_stream_emits_partial_text_when_enabled_without_duplication(self) -> None:
        captured_options = {}

        async def fake_query(**kwargs):
            captured_options.update(kwargs)
            yield _make_sdk_stream_event(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Hel"},
                }
            )
            yield _make_sdk_stream_event(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "lo"},
                }
            )
            yield _make_sdk_assistant_msg([_make_sdk_text_block("Hello")])
            yield _make_sdk_result_msg()

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            events = []
            async for event in stream_one_shot_query(
                "test",
                include_partial_messages=True,
            ):
                events.append(event)

        assert captured_options["options"].include_partial_messages is True
        assert [event.type for event in events] == ["text_delta", "text_delta", "done"]
        assert events[0].text == "Hel"
        assert events[1].text == "lo"
        assert events[2].text == "Hello"

    @pytest.mark.asyncio
    async def test_stream_emits_status_events_for_task_messages(self) -> None:
        async def fake_query(**kwargs):
            yield _make_sdk_task_started_msg("Research started")
            yield _make_sdk_task_progress_msg("Searching", last_tool_name="WebSearch")
            yield _make_sdk_task_notification_msg("Research complete")
            yield _make_sdk_result_msg()

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            events = []
            async for event in stream_one_shot_query("status test"):
                events.append(event)

        assert [event.type for event in events] == ["status", "status", "status", "done"]
        assert "Research started" in events[0].text
        assert "Searching" in events[1].text
        assert "Research complete" in events[2].text

    @pytest.mark.asyncio
    async def test_stream_emits_tool_events(self) -> None:
        async def fake_query(**kwargs):
            yield _make_sdk_assistant_msg(
                [
                    _make_sdk_tool_use_block(),
                    _make_sdk_tool_result_block(),
                ]
            )
            yield _make_sdk_result_msg()

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            events = []
            async for event in stream_one_shot_query("tool test"):
                events.append(event)

        assert [event.type for event in events] == [
            "tool_use_start",
            "tool_use_result",
            "done",
        ]
        assert events[0].tool_name == "calc"
        assert events[0].tool_input == {"expr": "2+2"}
        assert events[1].tool_result == "4"

    @pytest.mark.asyncio
    async def test_stream_without_result_message_emits_error(self) -> None:
        """Without ResultMessage stream_one_shot_query returns error, a not done."""

        async def fake_query(**kwargs):
            yield _make_sdk_assistant_msg([_make_sdk_text_block("partial")])

        with patch("swarmline.runtime.sdk_query._sdk_query", side_effect=fake_query):
            events = []
            async for event in stream_one_shot_query("missing final"):
                events.append(event)

        assert [event.type for event in events] == ["text_delta", "error"]
        assert "final ResultMessage" in events[-1].text
