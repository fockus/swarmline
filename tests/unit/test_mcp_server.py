"""Tests for MCP server assembly."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestCreateServer:
    def _make_fastmcp_mock(self):
        registered: list[str] = []

        mock_fastmcp_cls = MagicMock()
        mock_server = MagicMock()
        mock_fastmcp_cls.return_value = mock_server

        def _tool_factory(*args, **kwargs):
            def _decorator(fn):
                registered.append(fn.__name__)
                return fn

            return _decorator

        mock_server.tool = MagicMock(side_effect=_tool_factory)
        return mock_fastmcp_cls, mock_server, registered

    def test_create_server_headless_mode(self):
        mock_fastmcp_cls, mock_server, registered = self._make_fastmcp_mock()

        with patch.dict(
            "sys.modules", {"fastmcp": MagicMock(FastMCP=mock_fastmcp_cls)}
        ):
            from cognitia.mcp._server import create_server

            server = create_server(mode="headless")
            assert server is mock_server
            assert "cognitia_exec_code" not in registered
            mock_fastmcp_cls.assert_called_once()

    def test_create_server_full_mode(self):
        mock_fastmcp_cls, mock_server, registered = self._make_fastmcp_mock()

        with patch.dict(
            "sys.modules", {"fastmcp": MagicMock(FastMCP=mock_fastmcp_cls)}
        ):
            from cognitia.mcp._server import create_server

            server = create_server(mode="full")
            assert server is mock_server
            assert "cognitia_exec_code" not in registered

    def test_create_server_full_mode_enable_host_exec_registers_tool(self):
        mock_fastmcp_cls, mock_server, registered = self._make_fastmcp_mock()

        with patch.dict(
            "sys.modules", {"fastmcp": MagicMock(FastMCP=mock_fastmcp_cls)}
        ):
            from cognitia.mcp._server import create_server

            server = create_server(mode="full", enable_host_exec=True)
            assert server is mock_server
            assert "cognitia_exec_code" in registered

    def test_create_server_without_fastmcp_raises(self):
        with patch.dict("sys.modules", {"fastmcp": None}):
            import importlib
            from cognitia.mcp import _server

            importlib.reload(_server)
            with pytest.raises(ImportError, match="FastMCP is required"):
                _server.create_server(mode="headless")
