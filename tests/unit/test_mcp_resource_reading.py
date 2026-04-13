"""Tests for MCP resource reading (resources/list + resources/read) in McpClient."""

from __future__ import annotations

import time

import pytest

from swarmline.runtime.thin.mcp_client import McpClient, ResourceDescriptor


# ---------------------------------------------------------------------------
# Helpers — reusable fake httpx client/response
# ---------------------------------------------------------------------------


def _make_client_class(response_json: dict, *, fail: bool = False, error: Exception | None = None):
    """Build a fake httpx.AsyncClient that returns *response_json* or raises."""

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return response_json

    class _Client:
        calls: list[dict] = []

        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return None

        async def post(self, url, *, json=None, **kwargs):
            _ = kwargs
            _Client.calls.append({"url": url, "json": json})
            if fail:
                raise (error or RuntimeError("network down"))
            return _Response()

    _Client.calls = []
    return _Client


# ===========================================================================
# list_resources
# ===========================================================================


class TestListResources:
    """resources/list — discovery + caching."""

    @pytest.mark.asyncio
    async def test_list_resources_returns_descriptors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Basic list returns ResourceDescriptor objects with all fields."""
        fake = _make_client_class(
            {
                "result": {
                    "resources": [
                        {
                            "uri": "file:///readme.md",
                            "name": "README",
                            "description": "Project readme",
                            "mimeType": "text/markdown",
                        },
                        {
                            "uri": "db://users/schema",
                            "name": "Users schema",
                        },
                    ]
                }
            }
        )
        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fake)

        client = McpClient(timeout_seconds=1.0)
        resources = await client.list_resources("https://example.test/mcp")

        assert len(resources) == 2

        r0 = resources[0]
        assert isinstance(r0, ResourceDescriptor)
        assert r0.uri == "file:///readme.md"
        assert r0.name == "README"
        assert r0.description == "Project readme"
        assert r0.mime_type == "text/markdown"

        r1 = resources[1]
        assert r1.uri == "db://users/schema"
        assert r1.name == "Users schema"
        assert r1.description is None
        assert r1.mime_type is None

    @pytest.mark.asyncio
    async def test_list_resources_cache_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Repeated call within TTL uses cache (no second HTTP request)."""
        fake = _make_client_class(
            {"result": {"resources": [{"uri": "a://x", "name": "X"}]}}
        )
        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fake)

        client = McpClient(timeout_seconds=1.0, tools_cache_ttl_seconds=100.0)
        first = await client.list_resources("https://example.test/mcp")
        second = await client.list_resources("https://example.test/mcp")

        assert len(first) == 1
        assert len(second) == 1
        assert len(fake.calls) == 1  # only one HTTP call

    @pytest.mark.asyncio
    async def test_list_resources_cache_expired(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Call after TTL expiry makes a new request."""
        fake = _make_client_class(
            {"result": {"resources": [{"uri": "a://x", "name": "X"}]}}
        )
        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fake)

        client = McpClient(timeout_seconds=1.0, tools_cache_ttl_seconds=0.0)

        # Manually seed expired cache
        client._resources_cache["https://example.test/mcp"] = (
            time.monotonic() - 999,
            [ResourceDescriptor(uri="a://old")],
        )

        result = await client.list_resources("https://example.test/mcp")

        assert len(result) == 1
        assert result[0].uri == "a://x"
        assert len(fake.calls) == 1

    @pytest.mark.asyncio
    async def test_list_resources_force_refresh(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """force_refresh=True bypasses cache even if fresh."""
        fake = _make_client_class(
            {"result": {"resources": [{"uri": "a://new", "name": "New"}]}}
        )
        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fake)

        client = McpClient(timeout_seconds=1.0, tools_cache_ttl_seconds=9999.0)

        # Seed fresh cache
        client._resources_cache["https://example.test/mcp"] = (
            time.monotonic(),
            [ResourceDescriptor(uri="a://old")],
        )

        result = await client.list_resources("https://example.test/mcp", force_refresh=True)

        assert len(result) == 1
        assert result[0].uri == "a://new"
        assert len(fake.calls) == 1

    @pytest.mark.asyncio
    async def test_list_resources_network_error_returns_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Network failure with cached data returns stale cache."""
        fake = _make_client_class({}, fail=True)
        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fake)

        cached = [ResourceDescriptor(uri="a://cached", name="Cached")]
        client = McpClient(timeout_seconds=1.0)
        client._resources_cache["https://example.test/mcp"] = (time.monotonic() - 999, cached)

        result = await client.list_resources("https://example.test/mcp")

        assert len(result) == 1
        assert result[0].uri == "a://cached"

    @pytest.mark.asyncio
    async def test_list_resources_network_error_no_cache_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Network failure without cached data returns empty list (matches list_tools behavior)."""
        fake = _make_client_class({}, fail=True)
        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fake)

        client = McpClient(timeout_seconds=1.0)
        result = await client.list_resources("https://example.test/mcp")

        assert result == []


# ===========================================================================
# read_resource
# ===========================================================================


class TestReadResource:
    """resources/read — content retrieval."""

    @pytest.mark.asyncio
    async def test_read_resource_returns_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Successful read returns result dict with contents."""
        fake = _make_client_class(
            {
                "result": {
                    "contents": [
                        {"uri": "file:///readme.md", "text": "# Hello", "mimeType": "text/markdown"}
                    ]
                }
            }
        )
        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fake)

        client = McpClient(timeout_seconds=1.0)
        result = await client.read_resource("https://example.test/mcp", "file:///readme.md")

        assert isinstance(result, dict)
        assert "contents" in result
        assert len(result["contents"]) == 1
        assert result["contents"][0]["text"] == "# Hello"

    @pytest.mark.asyncio
    async def test_read_resource_text_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Text resource content is returned as-is."""
        fake = _make_client_class(
            {
                "result": {
                    "contents": [
                        {"uri": "config://app", "text": '{"debug": true}'}
                    ]
                }
            }
        )
        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fake)

        client = McpClient(timeout_seconds=1.0)
        result = await client.read_resource("https://example.test/mcp", "config://app")

        content = result["contents"][0]
        assert content["text"] == '{"debug": true}'
        assert "blob" not in content

    @pytest.mark.asyncio
    async def test_read_resource_blob_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Binary resource returns blob field."""
        fake = _make_client_class(
            {
                "result": {
                    "contents": [
                        {"uri": "file:///img.png", "blob": "iVBORw0KGgo=", "mimeType": "image/png"}
                    ]
                }
            }
        )
        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fake)

        client = McpClient(timeout_seconds=1.0)
        result = await client.read_resource("https://example.test/mcp", "file:///img.png")

        content = result["contents"][0]
        assert content["blob"] == "iVBORw0KGgo="
        assert "text" not in content

    @pytest.mark.asyncio
    async def test_read_resource_not_found_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-existent resource returns error dict."""
        fake = _make_client_class(
            {"error": {"code": -32602, "message": "Resource not found: missing://x"}}
        )
        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fake)

        client = McpClient(timeout_seconds=1.0)
        result = await client.read_resource("https://example.test/mcp", "missing://x")

        assert isinstance(result, dict)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_read_resource_server_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Server-side error returns error dict."""
        fake = _make_client_class({}, fail=True, error=RuntimeError("server exploded"))
        monkeypatch.setattr("swarmline.runtime.thin.mcp_client.httpx.AsyncClient", fake)

        client = McpClient(timeout_seconds=1.0)
        result = await client.read_resource("https://example.test/mcp", "db://users")

        assert isinstance(result, dict)
        assert "error" in result
