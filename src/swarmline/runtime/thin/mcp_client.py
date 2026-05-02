"""Mcp Client module."""

from __future__ import annotations

import importlib
import time
import uuid
from dataclasses import dataclass
from typing import Any

from swarmline.observability.redaction import redact_secrets
from swarmline.network_safety import validate_http_endpoint_url
from swarmline.runtime.types import ToolSpec

httpx: Any
try:
    httpx = importlib.import_module("httpx")
except ImportError:  # pragma: no cover - exercised via subprocess import test
    httpx = None


@dataclass(frozen=True)
class ResourceDescriptor:
    """Immutable descriptor for an MCP resource (resources/list item)."""

    uri: str
    name: str | None = None
    description: str | None = None
    mime_type: str | None = None


def resolve_mcp_server_url(
    servers: dict[str, Any],
    server_id: str,
) -> str | None:
    """Resolve server_id to URL string from a servers mapping.

    Supports:
    - str values (used as-is)
    - Objects with a `URL` attribute (MCPServerSpec-like)
    - None / missing -> None
    """
    server = servers.get(server_id)
    if server is None:
        return None
    if isinstance(server, str):
        return _validated_server_url(server)
    if isinstance(server, dict):
        url = server.get("url")
        if isinstance(url, str) and url:
            return _validated_server_url(
                url,
                allow_private_network=bool(server.get("allow_private_network", False)),
                allow_insecure_http=bool(server.get("allow_insecure_http", False)),
            )
    url = getattr(server, "url", None)
    if isinstance(url, str) and url:
        return _validated_server_url(
            url,
            allow_private_network=bool(getattr(server, "allow_private_network", False)),
            allow_insecure_http=bool(getattr(server, "allow_insecure_http", False)),
        )
    return None


def _validated_server_url(
    url: str,
    *,
    allow_private_network: bool = False,
    allow_insecure_http: bool = False,
) -> str | None:
    rejection = validate_http_endpoint_url(
        url,
        allow_private_network=allow_private_network,
        allow_insecure_http=allow_insecure_http,
    )
    if rejection:
        return None
    return url


def parse_mcp_tool_name(tool_name: str) -> tuple[str, str] | None:
    """Parse 'MCP__server__tool' into (server_id, remote_tool_name).

    Returns None if the format is invalid.
    Format: MCP__{server_id}__{tool_name} where both parts are non-empty.
    """
    parts = tool_name.split("__", 2)
    if len(parts) != 3 or parts[0] != "mcp" or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


class McpClient:
    """Mcp Client implementation."""

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        tools_cache_ttl_seconds: float = 300.0,
        resources_cache_ttl_seconds: float | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._tools_cache_ttl = tools_cache_ttl_seconds
        self._resources_cache_ttl = (
            resources_cache_ttl_seconds
            if resources_cache_ttl_seconds is not None
            else tools_cache_ttl_seconds
        )
        self._tools_cache: dict[str, tuple[float, list[ToolSpec]]] = {}
        self._resources_cache: dict[str, tuple[float, list[ResourceDescriptor]]] = {}
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> McpClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        _ = (exc_type, exc, tb)
        await self.aclose()

    def _get_http_client(self) -> httpx.AsyncClient:
        if httpx is None:
            raise RuntimeError(
                "httpx is not installed. Install swarmline[thin] or swarmline[all] "
                "to use MCP HTTP client features."
            )
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    @staticmethod
    def _is_httpx_timeout(exc: Exception) -> bool:
        return httpx is not None and isinstance(exc, httpx.TimeoutException)

    @staticmethod
    def _server_url_rejection(server_url: str) -> str | None:
        return validate_http_endpoint_url(server_url)

    async def aclose(self) -> None:
        """Close the pooled HTTP client, if it has been opened."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def call_tool(
        self,
        server_url: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Call tool."""
        rejection = self._server_url_rejection(server_url)
        if rejection:
            return {"error": f"MCP server URL rejected: {rejection}"}

        payload = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex[:8],
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
        }

        try:
            client = self._get_http_client()
            response = await client.post(
                server_url, json=payload, timeout=self._timeout
            )
            response.raise_for_status()
        except Exception as exc:
            if self._is_httpx_timeout(exc):
                return {"error": f"Таймаут при вызове MCP tool '{tool_name}'"}
            return {
                "error": f"HTTP ошибка MCP вызова '{tool_name}': {redact_secrets(str(exc))}"
            }

        try:
            data = response.json()
        except Exception as exc:
            return {"error": f"Некорректный JSON ответ MCP: {exc}"}

        if isinstance(data, dict) and data.get("error") is not None:
            return {"error": data["error"]}

        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return data

    async def list_tools(
        self,
        server_url: str,
        *,
        force_refresh: bool = False,
        request_timeout: float | None = None,
    ) -> list[ToolSpec]:
        """List tools."""
        rejection = self._server_url_rejection(server_url)
        if rejection:
            return []

        now = time.monotonic()
        cached = self._tools_cache.get(server_url)
        if (
            not force_refresh
            and cached is not None
            and (now - cached[0]) < self._tools_cache_ttl
        ):
            return cached[1]

        payload = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex[:8],
            "method": "tools/list",
            "params": {},
        }

        timeout_value = (
            request_timeout if request_timeout is not None else self._timeout
        )

        try:
            client = self._get_http_client()
            response = await client.post(
                server_url, json=payload, timeout=timeout_value
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            if cached is not None:
                return cached[1]
            return []

        tools = self._parse_tools_from_response(data)
        self._tools_cache[server_url] = (now, tools)
        return tools

    @staticmethod
    def _parse_tools_from_response(data: Any) -> list[ToolSpec]:
        """Parse tools from response."""

        # 1) {"result": {"tools": [...]}}
        # 2) {"result": [...]}
        # 3) {"tools": [...]}
        # 4) [...]
        raw_tools: Any = []

        if isinstance(data, dict):
            if isinstance(data.get("result"), dict):
                raw_tools = data["result"].get("tools", [])
            elif isinstance(data.get("result"), list):
                raw_tools = data["result"]
            elif isinstance(data.get("tools"), list):
                raw_tools = data["tools"]
        elif isinstance(data, list):
            raw_tools = data

        if not isinstance(raw_tools, list):
            return []

        parsed: list[ToolSpec] = []
        for item in raw_tools:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            description = (
                str(item.get("description", "")).strip() or f"MCP tool: {name}"
            )
            parameters = (
                item.get("input_schema")
                or item.get("inputSchema")
                or item.get("parameters")
            )
            if not isinstance(parameters, dict):
                parameters = {"type": "object"}
            parsed.append(
                ToolSpec(
                    name=name,
                    description=description,
                    parameters=parameters,
                    is_local=False,
                )
            )
        return parsed

    # ------------------------------------------------------------------
    # resources/list
    # ------------------------------------------------------------------

    async def list_resources(
        self,
        server_url: str,
        *,
        force_refresh: bool = False,
    ) -> list[ResourceDescriptor]:
        """Discover available MCP resources via resources/list.

        Uses the same TTL cache strategy as list_tools.
        On network error: returns stale cache if available, otherwise raises
        ConnectionError.
        """
        rejection = self._server_url_rejection(server_url)
        if rejection:
            return []

        now = time.monotonic()
        cached = self._resources_cache.get(server_url)
        if (
            not force_refresh
            and cached is not None
            and (now - cached[0]) < self._resources_cache_ttl
        ):
            return cached[1]

        payload = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex[:8],
            "method": "resources/list",
            "params": {},
        }

        try:
            client = self._get_http_client()
            response = await client.post(
                server_url, json=payload, timeout=self._timeout
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            if cached is not None:
                return cached[1]
            return []

        resources = self._parse_resources_from_response(data)
        self._resources_cache[server_url] = (now, resources)
        return resources

    @staticmethod
    def _parse_resources_from_response(data: Any) -> list[ResourceDescriptor]:
        """Extract ResourceDescriptor list from JSON-RPC response."""
        raw: Any = []

        if isinstance(data, dict):
            result = data.get("result")
            if isinstance(result, dict):
                raw = result.get("resources", [])
            elif isinstance(result, list):
                raw = result

        if not isinstance(raw, list):
            return []

        parsed: list[ResourceDescriptor] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            uri = item.get("uri")
            if not isinstance(uri, str) or not uri:
                continue
            parsed.append(
                ResourceDescriptor(
                    uri=uri,
                    name=item.get("name"),
                    description=item.get("description"),
                    mime_type=item.get("mimeType"),
                )
            )
        return parsed

    # ------------------------------------------------------------------
    # resources/read
    # ------------------------------------------------------------------

    async def read_resource(
        self,
        server_url: str,
        uri: str,
    ) -> dict[str, Any]:
        """Read a single MCP resource by URI via resources/read.

        Returns the result dict (contains 'contents' list with text/blob entries).
        On error returns {"error": <message>}.
        """
        if not uri or not uri.strip():
            return {"error": "Resource URI is required"}
        rejection = self._server_url_rejection(server_url)
        if rejection:
            return {"error": f"MCP server URL rejected: {rejection}"}

        payload = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex[:8],
            "method": "resources/read",
            "params": {"uri": uri},
        }

        try:
            client = self._get_http_client()
            response = await client.post(
                server_url, json=payload, timeout=self._timeout
            )
            response.raise_for_status()
        except Exception as exc:
            if self._is_httpx_timeout(exc):
                return {"error": f"Timeout reading MCP resource '{uri}'"}
            return {
                "error": f"HTTP error reading MCP resource '{uri}': {redact_secrets(str(exc))}"
            }

        try:
            data = response.json()
        except Exception as exc:
            return {"error": f"Invalid JSON from MCP resources/read: {exc}"}

        if isinstance(data, dict) and data.get("error") is not None:
            return {"error": data["error"]}

        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return data
