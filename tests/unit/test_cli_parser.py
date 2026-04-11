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
