"""Mcp Client module.

Supports two MCP transports, routed per-server by the resolved spec:

- HTTP JSON-RPC (``{"url": ...}`` specs / plain URL strings): stateless POST
  requests, no ``initialize`` handshake (many HTTP servers are stateless).
- stdio (``{"command": ..., "args": [...], "env": {...}}`` specs): a subprocess
  speaking newline-delimited JSON-RPC 2.0 over stdin/stdout per the MCP stdio
  transport, with the ``initialize`` handshake + ``notifications/initialized``.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from swarmline.observability.redaction import redact_secrets
from swarmline.network_safety import validate_http_endpoint_url
from swarmline.runtime._subprocess_env import build_subprocess_env
from swarmline.runtime.types import ToolSpec

httpx: Any
try:
    httpx = importlib.import_module("httpx")
except ImportError:  # pragma: no cover - exercised via subprocess import test
    httpx = None

MCP_PROTOCOL_VERSION = "2024-11-05"


def _client_version() -> str:
    try:
        from swarmline import __version__

        return __version__
    except Exception:  # pragma: no cover - metadata lookup is best-effort
        return "0.0.0-dev"


@dataclass(frozen=True)
class McpStdioServerSpec:
    """Resolved stdio MCP server spec (command + args + extra env).

    ``args`` and ``env`` are tuples so the spec is hashable and can key the
    tools/resources caches and the session registry.
    """

    command: str
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()

    @property
    def env_dict(self) -> dict[str, str]:
        """Extra environment variables as a plain dict."""
        return dict(self.env)


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


def _stdio_spec_from_parts(
    command: Any, args: Any, env: Any
) -> McpStdioServerSpec | None:
    if not isinstance(command, str) or not command.strip():
        return None
    arg_items: tuple[str, ...] = ()
    if isinstance(args, (list, tuple)):
        arg_items = tuple(str(a) for a in args)
    env_items: tuple[tuple[str, str], ...] = ()
    if isinstance(env, dict):
        env_items = tuple(sorted((str(k), str(v)) for k, v in env.items()))
    return McpStdioServerSpec(command=command, args=arg_items, env=env_items)


def resolve_mcp_server_spec(
    servers: dict[str, Any],
    server_id: str,
) -> str | McpStdioServerSpec | None:
    """Resolve server_id to a transport spec: HTTP URL string or stdio spec.

    Specs with a ``command`` (dict key or object attribute) resolve to
    :class:`McpStdioServerSpec`; everything else falls back to the existing
    URL resolution (``resolve_mcp_server_url``), preserving its validation.
    """
    server = servers.get(server_id)
    if server is None:
        return None
    if isinstance(server, dict):
        stdio = _stdio_spec_from_parts(
            server.get("command"), server.get("args"), server.get("env")
        )
        if stdio is not None:
            return stdio
    elif not isinstance(server, str):
        stdio = _stdio_spec_from_parts(
            getattr(server, "command", None),
            getattr(server, "args", None),
            getattr(server, "env", None),
        )
        if stdio is not None:
            return stdio
    return resolve_mcp_server_url(servers, server_id)


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


class _McpStdioSession:
    """One stdio MCP server subprocess with JSON-RPC 2.0 over stdin/stdout.

    Framing is newline-delimited JSON (the MCP stdio standard). The session
    lazily spawns the subprocess on first request and performs the
    ``initialize`` handshake followed by ``notifications/initialized``. If the
    process dies, the next request respawns and re-initializes it.
    """

    def __init__(self, spec: McpStdioServerSpec, timeout_seconds: float) -> None:
        self._spec = spec
        self._timeout = timeout_seconds
        self._proc: asyncio.subprocess.Process | None = None
        self._initialized = False
        self._next_id = 0
        self._lock = asyncio.Lock()

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and return the full response message.

        Serialized with a lock: the stdio pipe is a single ordered channel.
        Raises TimeoutError / ConnectionError / OSError on transport failures.
        """
        async with self._lock:
            await self._ensure_started()
            return await self._request(method, params)

    async def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            if self._initialized:
                return
            # Partial init (e.g. handshake timed out while the process kept
            # running): never talk to a server that missed
            # notifications/initialized — restart it cleanly instead.
            await self.aclose()
        self._initialized = False
        env = build_subprocess_env(
            inherit_host_env=True,
            env_allowlist=(),
            overrides=self._spec.env_dict,
        )
        self._proc = await asyncio.create_subprocess_exec(
            self._spec.command,
            *self._spec.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
        init_response = await self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "swarmline", "version": _client_version()},
            },
        )
        if init_response.get("error") is not None:
            await self.aclose()
            msg = f"MCP initialize failed: {init_response['error']}"
            raise ConnectionError(msg)
        await self._notify("notifications/initialized")
        self._initialized = True

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise ConnectionError("MCP stdio server is not running")
        self._next_id += 1
        request_id = self._next_id
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await proc.stdin.drain()

        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"MCP stdio request '{method}' timed out")
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            if not line:
                raise ConnectionError("MCP stdio server closed the connection")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # non-protocol noise on stdout
            if isinstance(message, dict) and message.get("id") == request_id:
                return message
            # Server-initiated notifications/requests are ignored (minimal client).

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise ConnectionError("MCP stdio server is not running")
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await proc.stdin.drain()

    async def aclose(self) -> None:
        """Gracefully stop the subprocess: close stdin, then terminate/kill."""
        proc = self._proc
        self._proc = None
        self._initialized = False
        if proc is None or proc.returncode is not None:
            return
        with contextlib.suppress(OSError):
            if proc.stdin is not None:
                proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
            return
        except TimeoutError:
            pass
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()


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
        self._tools_cache: dict[
            str | McpStdioServerSpec, tuple[float, list[ToolSpec]]
        ] = {}
        self._resources_cache: dict[
            str | McpStdioServerSpec, tuple[float, list[ResourceDescriptor]]
        ] = {}
        self._client: httpx.AsyncClient | None = None
        self._stdio_sessions: dict[McpStdioServerSpec, _McpStdioSession] = {}

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
        """Close the pooled HTTP client and all stdio server subprocesses."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        sessions = list(self._stdio_sessions.values())
        self._stdio_sessions.clear()
        for session in sessions:
            await session.aclose()

    # ------------------------------------------------------------------
    # stdio transport
    # ------------------------------------------------------------------

    def _get_stdio_session(self, spec: McpStdioServerSpec) -> _McpStdioSession:
        session = self._stdio_sessions.get(spec)
        if session is None:
            session = _McpStdioSession(spec, timeout_seconds=self._timeout)
            self._stdio_sessions[spec] = session
        return session

    async def _stdio_rpc(
        self,
        spec: McpStdioServerSpec,
        method: str,
        params: dict[str, Any],
    ) -> tuple[Any, Any]:
        """Perform one stdio JSON-RPC request.

        Returns ``(result, None)`` on success, ``(None, error)`` on failure —
        where error is the JSON-RPC error object or an error message string.
        """
        session = self._get_stdio_session(spec)
        try:
            message = await session.request(method, params)
        except TimeoutError:
            return None, f"Таймаут MCP stdio запроса '{method}'"
        except Exception as exc:
            return (
                None,
                f"MCP stdio ошибка '{method}': {redact_secrets(str(exc))}",
            )
        if message.get("error") is not None:
            return None, message["error"]
        return message.get("result"), None

    async def call_tool(
        self,
        server_url: str | McpStdioServerSpec,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Call tool."""
        if isinstance(server_url, McpStdioServerSpec):
            result, error = await self._stdio_rpc(
                server_url,
                "tools/call",
                {"name": tool_name, "arguments": arguments or {}},
            )
            if error is not None:
                return {"error": error}
            return result if result is not None else {}

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
        server_url: str | McpStdioServerSpec,
        *,
        force_refresh: bool = False,
        request_timeout: float | None = None,
    ) -> list[ToolSpec]:
        """List tools."""
        if isinstance(server_url, str):
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

        if isinstance(server_url, McpStdioServerSpec):
            result, error = await self._stdio_rpc(server_url, "tools/list", {})
            if error is not None:
                if cached is not None:
                    return cached[1]
                return []
            tools = self._parse_tools_from_response({"result": result})
            self._tools_cache[server_url] = (now, tools)
            return tools

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
        server_url: str | McpStdioServerSpec,
        *,
        force_refresh: bool = False,
    ) -> list[ResourceDescriptor]:
        """Discover available MCP resources via resources/list.

        Uses the same TTL cache strategy as list_tools.
        On network error: returns stale cache if available, otherwise raises
        ConnectionError.
        """
        if isinstance(server_url, str):
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

        if isinstance(server_url, McpStdioServerSpec):
            result, error = await self._stdio_rpc(server_url, "resources/list", {})
            if error is not None:
                if cached is not None:
                    return cached[1]
                return []
            resources = self._parse_resources_from_response({"result": result})
            self._resources_cache[server_url] = (now, resources)
            return resources

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
        server_url: str | McpStdioServerSpec,
        uri: str,
    ) -> dict[str, Any]:
        """Read a single MCP resource by URI via resources/read.

        Returns the result dict (contains 'contents' list with text/blob entries).
        On error returns {"error": <message>}.
        """
        if not uri or not uri.strip():
            return {"error": "Resource URI is required"}
        if isinstance(server_url, McpStdioServerSpec):
            result, error = await self._stdio_rpc(
                server_url, "resources/read", {"uri": uri}
            )
            if error is not None:
                return {"error": error}
            return result if isinstance(result, dict) else {}
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
