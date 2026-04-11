"""Mcp Client module."""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from swarmline.network_safety import validate_http_endpoint_url
from swarmline.runtime.types import ToolSpec


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
    ) -> None:
        self._timeout = timeout_seconds
        self._tools_cache_ttl = tools_cache_ttl_seconds
        self._tools_cache: dict[str, tuple[float, list[ToolSpec]]] = {}

    async def call_tool(
        self,
        server_url: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Call tool."""
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
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(server_url, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException:
            return {"error": f"Таймаут при вызове MCP tool '{tool_name}'"}
        except Exception as exc:
            return {"error": f"HTTP ошибка MCP вызова '{tool_name}': {exc}"}

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
        now = time.monotonic()
        cached = self._tools_cache.get(server_url)
        if not force_refresh and cached is not None and (now - cached[0]) < self._tools_cache_ttl:
            return cached[1]

        payload = {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex[:8],
            "method": "tools/list",
            "params": {},
        }

        timeout_value = request_timeout if request_timeout is not None else self._timeout

        try:
            async with httpx.AsyncClient(timeout=timeout_value) as client:
                response = await client.post(server_url, json=payload)
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
            description = str(item.get("description", "")).strip() or f"MCP tool: {name}"
            parameters = (
                item.get("input_schema") or item.get("inputSchema") or item.get("parameters")
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
