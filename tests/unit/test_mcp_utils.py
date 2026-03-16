"""Tests for MCP utility functions: resolve_mcp_server_url, parse_mcp_tool_name.

D7: resolve_mcp_server_url extracted from McpBridge._resolve_url / ToolExecutor._resolve_server_url.
D8: parse_mcp_tool_name extracted from ToolExecutor._parse_mcp_tool_name / DeepAgentsRuntime inline split.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest


class TestResolveMcpServerUrl:
    """resolve_mcp_server_url(servers, server_id) -> str | None."""

    def test_resolve_string_url(self) -> None:
        from cognitia.runtime.thin.mcp_client import resolve_mcp_server_url

        servers = {"srv": "http://localhost:8080"}
        assert resolve_mcp_server_url(servers, "srv") == "http://localhost:8080"

    def test_resolve_object_with_url_attr(self) -> None:
        from cognitia.runtime.thin.mcp_client import resolve_mcp_server_url

        @dataclass
        class Spec:
            url: str

        servers = {"srv": Spec(url="http://example.com")}
        assert resolve_mcp_server_url(servers, "srv") == "http://example.com"

    def test_resolve_missing_server_returns_none(self) -> None:
        from cognitia.runtime.thin.mcp_client import resolve_mcp_server_url

        assert resolve_mcp_server_url({}, "nonexistent") is None

    def test_resolve_object_without_url_returns_none(self) -> None:
        from cognitia.runtime.thin.mcp_client import resolve_mcp_server_url

        servers = {"srv": 12345}
        assert resolve_mcp_server_url(servers, "srv") is None

    def test_resolve_empty_url_string_returns_none(self) -> None:
        from cognitia.runtime.thin.mcp_client import resolve_mcp_server_url

        @dataclass
        class Spec:
            url: str

        servers = {"srv": Spec(url="")}
        assert resolve_mcp_server_url(servers, "srv") is None

    def test_resolve_none_value_returns_none(self) -> None:
        from cognitia.runtime.thin.mcp_client import resolve_mcp_server_url

        servers: dict[str, object] = {"srv": None}
        assert resolve_mcp_server_url(servers, "srv") is None


class TestParseMcpToolName:
    """parse_mcp_tool_name(tool_name) -> (server_id, remote_tool) | None."""

    @pytest.mark.parametrize(
        ("tool_name", "expected"),
        [
            ("mcp__server__tool", ("server", "tool")),
            ("mcp__my_srv__calc_sum", ("my_srv", "calc_sum")),
            ("mcp__a__b__c", ("a", "b__c")),
        ],
    )
    def test_parse_valid_names(self, tool_name: str, expected: tuple[str, str]) -> None:
        from cognitia.runtime.thin.mcp_client import parse_mcp_tool_name

        assert parse_mcp_tool_name(tool_name) == expected

    @pytest.mark.parametrize(
        "tool_name",
        [
            "local_tool",
            "mcp__",
            "mcp____tool",
            "mcp__server__",
            "notmcp__server__tool",
            "",
        ],
    )
    def test_parse_invalid_names_return_none(self, tool_name: str) -> None:
        from cognitia.runtime.thin.mcp_client import parse_mcp_tool_name

        assert parse_mcp_tool_name(tool_name) is None
