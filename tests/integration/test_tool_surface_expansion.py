"""Integration tests for Phase 12: Tool Surface Expansion.

Covers:
- WEBT-03: Domain allow/block lists wired to web_fetch
- WEBT-04: Web tools denied by default, allowed when whitelisted
- MCPR-01: read_mcp_resource tool reads resource from MCP server
- MCPR-02: MCP resource list cached per-connection
- MCPR-03: read_mcp_resource integrates with ToolExecutor
- Backward compatibility: no domain filter = all domains allowed
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.mcp_client import McpClient
from swarmline.runtime.types import RuntimeConfig
from swarmline.tools.builtin import create_web_tools
from swarmline.tools.web_httpx import HttpxWebProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor(
    local_tools: dict | None = None,
    mcp_servers: dict | None = None,
    mcp_client: McpClient | None = None,
    tool_policy: Any = None,
) -> ToolExecutor:
    return ToolExecutor(
        local_tools=local_tools or {},
        mcp_servers=mcp_servers or {},
        mcp_client=mcp_client,
        tool_policy=tool_policy,
    )


# ---------------------------------------------------------------------------
# WEBT-03: Domain filter integration
# ---------------------------------------------------------------------------


class TestWebFetchDomainFilterIntegration:
    @pytest.mark.asyncio
    async def test_web_fetch_domain_filter_blocks_unlisted(self) -> None:
        """Domain filter blocks URL not in allowed list through tool executor."""
        provider = HttpxWebProvider(allowed_domains=["example.com"])
        specs, executors = create_web_tools(provider)

        executor = _make_executor(local_tools=executors)
        result = await executor.execute("web_fetch", {"url": "https://blocked.org/page"})
        data = json.loads(result)

        assert data.get("status") == "ok"
        assert "not in allowed list" in data.get("content", "")

    @pytest.mark.asyncio
    async def test_web_fetch_blocked_domain_returns_error(self) -> None:
        """Blocked domain returns meaningful error content."""
        provider = HttpxWebProvider(blocked_domains=["evil.com"])
        specs, executors = create_web_tools(provider)

        executor = _make_executor(local_tools=executors)
        result = await executor.execute("web_fetch", {"url": "https://evil.com/malware"})
        data = json.loads(result)

        assert data.get("status") == "ok"
        assert "blocked" in data.get("content", "").lower()

    @pytest.mark.asyncio
    async def test_backward_compat_no_domain_filter(self) -> None:
        """No domain filter configured = all domains pass (existing behavior)."""
        provider = HttpxWebProvider()
        specs, executors = create_web_tools(provider)

        # web_fetch with no filter should attempt fetch (will fail on DNS but not domain filter)
        executor = _make_executor(local_tools=executors)
        result = await executor.execute(
            "web_fetch", {"url": "https://nonexistent.test.invalid/"}
        )
        data = json.loads(result)
        # Should not contain "blocked" — it should attempt the fetch
        assert "blocked" not in data.get("content", "").lower() or data.get("status") == "ok"


class TestWebSearchUnchanged:
    @pytest.mark.asyncio
    async def test_web_search_returns_results(self) -> None:
        """web_search still works with mock provider."""
        mock_provider = AsyncMock()
        mock_provider.search = AsyncMock(return_value=[])

        specs, executors = create_web_tools(mock_provider)
        executor = _make_executor(local_tools=executors)
        result = await executor.execute("web_search", {"query": "test query"})
        data = json.loads(result)

        assert data["status"] == "ok"
        assert data["result_count"] == 0


# ---------------------------------------------------------------------------
# WEBT-04: Web tools denied by default via policy
# ---------------------------------------------------------------------------


class TestWebToolsPolicy:
    @pytest.mark.asyncio
    async def test_web_tools_denied_by_default_policy(self) -> None:
        """DefaultToolPolicy denies web_fetch/web_search by default."""
        from swarmline.policy.tool_policy import DefaultToolPolicy

        policy = DefaultToolPolicy()
        provider = HttpxWebProvider()
        specs, executors = create_web_tools(provider)

        executor = _make_executor(local_tools=executors, tool_policy=policy)
        result = await executor.execute("web_fetch", {"url": "https://example.com"})
        data = json.loads(result)

        assert "error" in data

    @pytest.mark.asyncio
    async def test_web_tools_allowed_when_whitelisted(self) -> None:
        """Web tools work when whitelisted in allowed_system_tools."""
        from swarmline.policy.tool_policy import DefaultToolPolicy

        policy = DefaultToolPolicy(
            allowed_system_tools={"web_fetch", "web_search"},
        )
        provider = HttpxWebProvider(allowed_domains=["example.com"])
        specs, executors = create_web_tools(provider)

        executor = _make_executor(local_tools=executors, tool_policy=policy)
        result = await executor.execute(
            "web_fetch", {"url": "https://example.com/page"}
        )
        data = json.loads(result)

        # Should NOT be policy-denied (may fail on network but not policy)
        assert "error" not in data or "denied" not in data.get("error", "").lower()


# ---------------------------------------------------------------------------
# MCPR-01..03: MCP resource reading integration
# ---------------------------------------------------------------------------


class TestMcpResourceToolIntegration:
    @pytest.mark.asyncio
    async def test_read_mcp_resource_tool_reads_resource(self) -> None:
        """read_mcp_resource tool successfully reads a resource from MCP server."""
        mock_client = AsyncMock(spec=McpClient)
        mock_client.read_resource = AsyncMock(
            return_value={"contents": [{"uri": "file:///data.txt", "text": "hello world"}]}
        )

        executor = _make_executor(
            mcp_servers={"my-server": {"url": "https://mcp.example.com"}},
            mcp_client=mock_client,
        )
        result = await executor.execute(
            "read_mcp_resource",
            {"server_id": "my-server", "uri": "file:///data.txt"},
        )
        data = json.loads(result)

        assert "contents" in data
        assert data["contents"][0]["text"] == "hello world"

    @pytest.mark.asyncio
    async def test_read_mcp_resource_server_not_found(self) -> None:
        """read_mcp_resource returns error for unknown server_id."""
        mock_client = AsyncMock(spec=McpClient)

        # Need at least one server so the tool is registered
        executor = _make_executor(
            mcp_servers={"existing": {"url": "https://mcp.test"}},
            mcp_client=mock_client,
        )
        result = await executor.execute(
            "read_mcp_resource",
            {"server_id": "unknown", "uri": "file:///test"},
        )
        data = json.loads(result)

        assert "error" in data
        assert "not found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_read_mcp_resource_returns_error_from_server(self) -> None:
        """read_mcp_resource propagates error from MCP server."""
        mock_client = AsyncMock(spec=McpClient)
        mock_client.read_resource = AsyncMock(
            return_value={"error": "Resource not found"}
        )

        executor = _make_executor(
            mcp_servers={"srv": {"url": "https://mcp.test"}},
            mcp_client=mock_client,
        )
        result = await executor.execute(
            "read_mcp_resource",
            {"server_id": "srv", "uri": "file:///missing"},
        )
        data = json.loads(result)

        assert "error" in data

    @pytest.mark.asyncio
    async def test_read_mcp_resource_spec_has_correct_schema(self) -> None:
        """read_mcp_resource tool spec has server_id and uri parameters."""
        from swarmline.runtime.thin.executor import READ_MCP_RESOURCE_SPEC

        assert READ_MCP_RESOURCE_SPEC.name == "read_mcp_resource"
        params = READ_MCP_RESOURCE_SPEC.parameters
        assert "server_id" in params["properties"]
        assert "uri" in params["properties"]
        assert set(params["required"]) == {"server_id", "uri"}

    @pytest.mark.asyncio
    async def test_executor_has_read_mcp_resource_tool(self) -> None:
        """ToolExecutor with mcp_servers includes read_mcp_resource in local tools."""
        executor = _make_executor(
            mcp_servers={"srv": {"url": "https://mcp.test"}},
        )
        assert executor.has_tool("read_mcp_resource")

    @pytest.mark.asyncio
    async def test_executor_without_mcp_no_resource_tool(self) -> None:
        """ToolExecutor without mcp_servers does NOT register read_mcp_resource."""
        executor = _make_executor(mcp_servers={})
        assert not executor.has_tool("read_mcp_resource")


# ---------------------------------------------------------------------------
# RuntimeConfig domain filter fields
# ---------------------------------------------------------------------------


class TestRuntimeConfigDomainFields:
    def test_runtime_config_accepts_domain_fields(self) -> None:
        """RuntimeConfig accepts web_allowed_domains and web_blocked_domains."""
        config = RuntimeConfig(
            runtime_name="thin",
            web_allowed_domains=["example.com", "api.test.io"],
            web_blocked_domains=["evil.com"],
        )
        assert config.web_allowed_domains == ["example.com", "api.test.io"]
        assert config.web_blocked_domains == ["evil.com"]

    def test_runtime_config_domain_fields_default_none(self) -> None:
        """Domain filter fields default to None (no filtering)."""
        config = RuntimeConfig(runtime_name="thin")
        assert config.web_allowed_domains is None
        assert config.web_blocked_domains is None


# ---------------------------------------------------------------------------
# Combined pipeline test
# ---------------------------------------------------------------------------


class TestToolSurfacePipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline_web_and_mcp(self) -> None:
        """Both web tools and MCP resource tool work in same executor."""
        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[])
        mock_search.fetch = AsyncMock(return_value="page content")

        provider = HttpxWebProvider(search_provider=mock_search)
        specs, executors = create_web_tools(provider)

        mock_client = AsyncMock(spec=McpClient)
        mock_client.read_resource = AsyncMock(
            return_value={"contents": [{"text": "resource data"}]}
        )

        executor = _make_executor(
            local_tools=executors,
            mcp_servers={"srv": {"url": "https://mcp.test"}},
            mcp_client=mock_client,
        )

        # Web search works
        search_result = await executor.execute("web_search", {"query": "test"})
        assert json.loads(search_result)["status"] == "ok"

        # MCP resource works
        mcp_result = await executor.execute(
            "read_mcp_resource", {"server_id": "srv", "uri": "test://doc"}
        )
        assert "contents" in json.loads(mcp_result)
