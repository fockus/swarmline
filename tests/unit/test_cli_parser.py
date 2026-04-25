"""Unit tests for NdjsonParser protocol and implementations."""

from __future__ import annotations

import json


class TestNdjsonParserProtocol:
    """NdjsonParser protocol compliance."""

    def test_ndjson_parser_protocol_claude_isinstance(self) -> None:
        """ClaudeNdjsonParser satisfies NdjsonParser Protocol."""
        from swarmline.runtime.cli.parser import ClaudeNdjsonParser, NdjsonParser

        assert isinstance(ClaudeNdjsonParser(), NdjsonParser)

    def test_ndjson_parser_protocol_generic_isinstance(self) -> None:
        """GenericNdjsonParser satisfies NdjsonParser Protocol."""
        from swarmline.runtime.cli.parser import GenericNdjsonParser, NdjsonParser

        assert isinstance(GenericNdjsonParser(), NdjsonParser)

    def test_ndjson_parser_protocol_pi_rpc_isinstance(self) -> None:
        """PiRpcParser satisfies NdjsonParser Protocol."""
        from swarmline.runtime.cli.parser import NdjsonParser, PiRpcParser

        assert isinstance(PiRpcParser(), NdjsonParser)


class TestClaudeNdjsonParser:
    """ClaudeNdjsonParser maps Claude Code NDJSON to RuntimeEvent."""

    def test_claude_parser_assistant_text_event(self) -> None:
        """assistant message with text content -> assistant_delta."""
        from swarmline.runtime.cli.parser import ClaudeNdjsonParser

        parser = ClaudeNdjsonParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "Hello world"}],
                },
            }
        )
        event = parser.parse_line(line)
        assert event is not None
        assert event.type == "assistant_delta"
        assert event.data["text"] == "Hello world"

    def test_claude_parser_tool_use_event(self) -> None:
        """assistant message with tool_use content -> tool_call_started."""
        from swarmline.runtime.cli.parser import ClaudeNdjsonParser

        parser = ClaudeNdjsonParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "read_file",
                            "input": {"path": "/tmp/test.py"},
                        }
                    ],
                },
            }
        )
        event = parser.parse_line(line)
        assert event is not None
        assert event.type == "tool_call_started"
        assert event.data["name"] == "read_file"
        assert event.data["args"] == {"path": "/tmp/test.py"}

    def test_claude_parser_result_event(self) -> None:
        """result type -> final event."""
        from swarmline.runtime.cli.parser import ClaudeNdjsonParser

        parser = ClaudeNdjsonParser()
        line = json.dumps({"type": "result", "result": "Final answer here"})
        event = parser.parse_line(line)
        assert event is not None
        assert event.type == "final"
        assert event.data["text"] == "Final answer here"

    def test_claude_parser_invalid_json_returns_none(self) -> None:
        """Malformed JSON line -> None."""
        from swarmline.runtime.cli.parser import ClaudeNdjsonParser

        parser = ClaudeNdjsonParser()
        assert parser.parse_line("not valid json {{{") is None

    def test_claude_parser_unknown_type_returns_none(self) -> None:
        """Unknown event type -> None."""
        from swarmline.runtime.cli.parser import ClaudeNdjsonParser

        parser = ClaudeNdjsonParser()
        line = json.dumps({"type": "ping", "data": {}})
        assert parser.parse_line(line) is None

    def test_claude_parser_empty_content_returns_none(self) -> None:
        """assistant message with empty content list -> None."""
        from swarmline.runtime.cli.parser import ClaudeNdjsonParser

        parser = ClaudeNdjsonParser()
        line = json.dumps({"type": "assistant", "message": {"content": []}})
        assert parser.parse_line(line) is None

    def test_claude_parser_empty_line_returns_none(self) -> None:
        """Empty string -> None."""
        from swarmline.runtime.cli.parser import ClaudeNdjsonParser

        parser = ClaudeNdjsonParser()
        assert parser.parse_line("") is None


class TestGenericNdjsonParser:
    """GenericNdjsonParser wraps raw JSON as RuntimeEvent."""

    def test_generic_parser_valid_json_passthrough(self) -> None:
        """Valid JSON -> status event with parsed data."""
        from swarmline.runtime.cli.parser import GenericNdjsonParser

        parser = GenericNdjsonParser()
        line = json.dumps({"foo": "bar", "count": 42})
        event = parser.parse_line(line)
        assert event is not None
        assert event.type == "status"
        assert event.data["foo"] == "bar"
        assert event.data["count"] == 42

    def test_generic_parser_invalid_json_returns_none(self) -> None:
        """Invalid JSON -> None."""
        from swarmline.runtime.cli.parser import GenericNdjsonParser

        parser = GenericNdjsonParser()
        assert parser.parse_line("not json") is None

    def test_generic_parser_empty_line_returns_none(self) -> None:
        """Empty line -> None."""
        from swarmline.runtime.cli.parser import GenericNdjsonParser

        parser = GenericNdjsonParser()
        assert parser.parse_line("") is None


class TestPiRpcParser:
    """PiRpcParser maps PI RPC JSONL events to RuntimeEvent."""

    def test_message_update_text_delta(self) -> None:
        from swarmline.runtime.cli.parser import PiRpcParser

        parser = PiRpcParser()
        line = json.dumps(
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": "hello"},
            }
        )

        event = parser.parse_line(line)

        assert event is not None
        assert event.type == "assistant_delta"
        assert event.data["text"] == "hello"

    def test_message_update_thinking_delta(self) -> None:
        from swarmline.runtime.cli.parser import PiRpcParser

        parser = PiRpcParser()
        line = json.dumps(
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "thinking_delta", "delta": "plan"},
            }
        )

        event = parser.parse_line(line)

        assert event is not None
        assert event.type == "thinking_delta"
        assert event.data["text"] == "plan"

    def test_tool_execution_events(self) -> None:
        from swarmline.runtime.cli.parser import PiRpcParser

        parser = PiRpcParser()
        started = parser.parse_line(
            json.dumps(
                {
                    "type": "tool_execution_start",
                    "toolCallId": "call-1",
                    "toolName": "bash",
                    "args": {"command": "pwd"},
                }
            )
        )
        finished = parser.parse_line(
            json.dumps(
                {
                    "type": "tool_execution_end",
                    "toolCallId": "call-1",
                    "toolName": "bash",
                    "result": {"content": [{"type": "text", "text": "/tmp"}]},
                    "isError": False,
                }
            )
        )

        assert started is not None
        assert started.type == "tool_call_started"
        assert started.data["name"] == "bash"
        assert started.data["correlation_id"] == "call-1"
        assert finished is not None
        assert finished.type == "tool_call_finished"
        assert finished.data["ok"] is True
        assert "/tmp" in finished.data["result_summary"]

    def test_agent_end_extracts_last_assistant_text(self) -> None:
        from swarmline.runtime.cli.parser import PiRpcParser

        parser = PiRpcParser()
        line = json.dumps(
            {
                "type": "agent_end",
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "done"},
                ],
            }
        )

        event = parser.parse_line(line)

        assert event is not None
        assert event.type == "final"
        assert event.data["text"] == "done"

    def test_failed_response_maps_to_error(self) -> None:
        from swarmline.runtime.cli.parser import PiRpcParser

        parser = PiRpcParser()
        line = json.dumps(
            {"type": "response", "command": "prompt", "success": False, "error": "bad"}
        )

        event = parser.parse_line(line)

        assert event is not None
        assert event.type == "error"
        assert event.data["kind"] == "runtime_crash"
        assert "bad" in event.data["message"]
