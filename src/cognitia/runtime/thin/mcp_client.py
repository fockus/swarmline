"""McpClient — lightweight JSON-RPC клиент для MCP серверов.

Поддерживает:
- tools/call
- tools/list (discovery) + in-memory cache

Module-level utilities (D7, D8):
- resolve_mcp_server_url — resolve server_id to URL from servers dict.
- parse_mcp_tool_name — parse "mcp__server__tool" into (server_id, tool_name).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from cognitia.runtime.types import ToolSpec


def resolve_mcp_server_url(
    servers: dict[str, Any],
    server_id: str,
) -> str | None:
    """Resolve server_id to URL string from a servers mapping.

    Supports:
    - str values (used as-is)
    - Objects with a `url` attribute (McpServerSpec-like)
    - None / missing -> None
    """
    server = servers.get(server_id)
    if server is None:
        return None
    if isinstance(server, str):
        return server
    url = getattr(server, "url", None)
    if isinstance(url, str) and url:
        return url
    return None


def parse_mcp_tool_name(tool_name: str) -> tuple[str, str] | None:
    """Parse 'mcp__server__tool' into (server_id, remote_tool_name).

    Returns None if the format is invalid.
    Format: mcp__{server_id}__{tool_name} where both parts are non-empty.
    """
    parts = tool_name.split("__", 2)
    if len(parts) != 3 or parts[0] != "mcp" or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


class McpClient:
    """Клиент MCP JSON-RPC по HTTP(S).

    Args:
        timeout_seconds: Таймаут HTTP вызова.
        tools_cache_ttl_seconds: TTL кеша tools/list по server_url.
    """

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
        """Вызвать MCP tool через JSON-RPC method=tools/call.

        Returns:
            payload из `result` или объект ошибки вида {"error": ...}.
        """
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
        """Получить список tools с MCP сервера (method=tools/list).

        Кеширует результат по `server_url` на `tools_cache_ttl_seconds`.
        При ошибке возвращает кеш (если есть), иначе пустой список.
        """
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
        """Нормализовать разные форматы ответа tools/list в list[ToolSpec]."""
        # Возможные форматы:
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
