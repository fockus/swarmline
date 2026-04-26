"""Tests for ToolIdCodec (sektsiya 4.4 arhitektury). Obespechivaet normalizatsiyu tool_name ↔ server_id
with uchetom defisov/podcherkivaniy and prefiksov mcp__.
"""

import pytest
from swarmline.policy.tool_id_codec import DefaultToolIdCodec


@pytest.fixture
def codec() -> DefaultToolIdCodec:
    return DefaultToolIdCodec()


class TestMatches:
    """matches(tool_name, server_id) - check prinadlezhnosti tool k serveru."""

    def test_exact_match(self, codec: DefaultToolIdCodec) -> None:
        """mcp__iss__get_emitent_id prinadlezhit serveru 'iss'."""
        assert codec.matches("mcp__iss__get_emitent_id", "iss") is True

    def test_hyphen_server(self, codec: DefaultToolIdCodec) -> None:
        """mcp__iss-price__get_price_time_series prinadlezhit serveru 'iss-price'."""
        assert (
            codec.matches("mcp__iss-price__get_price_time_series", "iss-price") is True
        )

    def test_no_match(self, codec: DefaultToolIdCodec) -> None:
        """mcp__iss__get_emitent_id NE prinadlezhit serveru 'funds'."""
        assert codec.matches("mcp__iss__get_emitent_id", "funds") is False

    def test_not_mcp_tool(self, codec: DefaultToolIdCodec) -> None:
        """Bash - not MCP tool, not prinadlezhit nikakomu serveru."""
        assert codec.matches("Bash", "iss") is False

    def test_local_tool_not_matches_server(self, codec: DefaultToolIdCodec) -> None:
        """Local tool mcp__freedom_tools__calc not prinadlezhit serveru 'iss'."""
        assert codec.matches("mcp__freedom_tools__calculate_goal_plan", "iss") is False

    def test_local_tool_matches_own_server(self, codec: DefaultToolIdCodec) -> None:
        """Local tool matches freedom_tools server."""
        assert (
            codec.matches("mcp__freedom_tools__calculate_goal_plan", "freedom_tools")
            is True
        )


class TestEncode:
    """encode(server_id, tool_name) - postroenie polnogo tool_name."""

    def test_encode_simple(self, codec: DefaultToolIdCodec) -> None:
        """Simple server + tool -> mcp__server__tool."""
        result = codec.encode("iss", "get_emitent_id")
        assert result == "mcp__iss__get_emitent_id"

    def test_encode_hyphen_server(self, codec: DefaultToolIdCodec) -> None:
        """Server with defisom."""
        result = codec.encode("iss-price", "get_price_time_series")
        assert result == "mcp__iss-price__get_price_time_series"


class TestExtractServer:
    """extract_server(tool_name) - izvlech server_id from tool_name."""

    def test_extract_simple(self, codec: DefaultToolIdCodec) -> None:
        """Izvlech 'iss' from 'mcp__iss__get_emitent_id'."""
        assert codec.extract_server("mcp__iss__get_emitent_id") == "iss"

    def test_extract_hyphen(self, codec: DefaultToolIdCodec) -> None:
        """Izvlech 'iss-price' from 'mcp__iss-price__get_price_time_series'."""
        assert (
            codec.extract_server("mcp__iss-price__get_price_time_series") == "iss-price"
        )

    def test_extract_not_mcp(self, codec: DefaultToolIdCodec) -> None:
        """Not MCP tool -> None."""
        assert codec.extract_server("Bash") is None

    def test_extract_malformed(self, codec: DefaultToolIdCodec) -> None:
        """Notcorrect format -> None."""
        assert codec.extract_server("mcp__only_one_part") is None


class TestEdgeCases:
    """Edge cases: empty strings, mnozhestvennye razdeliteli, spetssimvoly."""

    def test_empty_tool_name(self, codec: DefaultToolIdCodec) -> None:
        """Empty string -> None."""
        assert codec.extract_server("") is None

    def test_only_mcp_prefix(self, codec: DefaultToolIdCodec) -> None:
        """Tolko 'mcp__' without servera -> None."""
        assert codec.extract_server("mcp__") is None

    def test_mcp_double_underscore_empty_server(
        self, codec: DefaultToolIdCodec
    ) -> None:
        """'mcp____tool' - empty server_id -> None (idx=0, return None)."""
        assert codec.extract_server("mcp____tool") is None

    def test_tool_name_with_underscores(self, codec: DefaultToolIdCodec) -> None:
        """Tool name with podcherkivaniyami: 'mcp__iss__get_emitent_id_full'."""
        result = codec.extract_server("mcp__iss__get_emitent_id_full")
        assert result == "iss"

    def test_tool_with_multiple_double_underscores(
        self, codec: DefaultToolIdCodec
    ) -> None:
        """'mcp__server__tool__extra' - tolko pervyy __ razdelyaet server/tool."""
        result = codec.extract_server("mcp__server__tool__extra")
        assert result == "server"

    def test_matches_empty_server_id(self, codec: DefaultToolIdCodec) -> None:
        """Empty server_id -> False."""
        assert codec.matches("mcp__iss__get_bonds", "") is False

    def test_encode_roundtrip(self, codec: DefaultToolIdCodec) -> None:
        """encode + extract_server = roundtrip."""
        encoded = codec.encode("iss-price", "search_bonds")
        extracted = codec.extract_server(encoded)
        assert extracted == "iss-price"

    def test_matches_roundtrip(self, codec: DefaultToolIdCodec) -> None:
        """encode + matches = True."""
        encoded = codec.encode("funds", "get_fund_info")
        assert codec.matches(encoded, "funds") is True
        assert codec.matches(encoded, "iss") is False

    def test_no_mcp_prefix_with_double_underscore(
        self, codec: DefaultToolIdCodec
    ) -> None:
        """'notmcp__server__tool' -> None (nott mcp__ prefiksa)."""
        assert codec.extract_server("notmcp__server__tool") is None

    def test_server_with_numbers(self, codec: DefaultToolIdCodec) -> None:
        """Server ID with tsiframi: 'server123'."""
        encoded = codec.encode("server123", "tool")
        assert codec.extract_server(encoded) == "server123"
        assert codec.matches(encoded, "server123") is True
