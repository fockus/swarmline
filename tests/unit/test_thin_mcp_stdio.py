"""Tests for the stdio MCP transport (RUNTIME-PARITY B5, thin runtime).

Spawns a tiny real MCP server subprocess (newline-delimited JSON-RPC 2.0 over
stdin/stdout) and exercises the full path: spec resolution, initialize
handshake, tools/list (+TTL cache), tools/call, resources, env merging,
timeouts, and graceful process cleanup.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.mcp_client import (
    McpClient,
    McpStdioServerSpec,
    resolve_mcp_server_spec,
)

FAKE_SERVER = """
import json, os, sys

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\\n")
    sys.stdout.flush()

# Non-protocol noise on stdout: a robust client must skip it.
print("fake-mcp-server booting", flush=True)

initialized = False
list_count = 0

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    if method == "initialize":
        assert params.get("protocolVersion"), "client must send protocolVersion"
        assert params.get("clientInfo", {}).get("name") == "swarmline"
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": params["protocolVersion"],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-mcp", "version": "1.0"},
        }})
    elif method == "notifications/initialized":
        initialized = True
    elif method == "tools/list":
        assert initialized, "tools/list before notifications/initialized"
        list_count += 1
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            {"name": "echo", "description": "Echo text back",
             "inputSchema": {"type": "object",
                             "properties": {"text": {"type": "string"}}}},
        ]}})
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [
                {"type": "text", "text": "echo:" + args.get("text", "")}]}})
        elif name == "env":
            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [
                {"type": "text",
                 "text": os.environ.get("MCP_STDIO_TEST_ENV", "<unset>")}]}})
        elif name == "list_count":
            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [
                {"type": "text", "text": str(list_count)}]}})
        elif name == "sleep":
            continue  # never answer -> client must time out
        else:
            send({"jsonrpc": "2.0", "id": mid,
                  "error": {"code": -32601, "message": "unknown tool: " + str(name)}})
    elif method == "resources/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"resources": [
            {"uri": "mem://doc", "name": "doc", "mimeType": "text/plain"}]}})
    elif method == "resources/read":
        send({"jsonrpc": "2.0", "id": mid, "result": {"contents": [
            {"uri": params.get("uri"), "text": "resource-body"}]}})
    else:
        send({"jsonrpc": "2.0", "id": mid,
              "error": {"code": -32601, "message": "unknown method"}})
"""


@pytest.fixture
def server_script(tmp_path: Path) -> str:
    path = tmp_path / "fake_mcp_server.py"
    path.write_text(FAKE_SERVER)
    return str(path)


@pytest.fixture
def stdio_spec(server_script: str) -> McpStdioServerSpec:
    return McpStdioServerSpec(command=sys.executable, args=(server_script,))


class TestSpecResolution:
    def test_command_dict_resolves_to_stdio_spec(self) -> None:
        servers = {
            "local": {
                "command": "python",
                "args": ["server.py", "--flag"],
                "env": {"A": "1"},
            }
        }
        spec = resolve_mcp_server_spec(servers, "local")
        assert isinstance(spec, McpStdioServerSpec)
        assert spec.command == "python"
        assert spec.args == ("server.py", "--flag")
        assert spec.env_dict == {"A": "1"}

    def test_command_object_resolves_to_stdio_spec(self) -> None:
        class _Spec:
            command = "npx"
            args = ["-y", "some-server"]
            env = None

        spec = resolve_mcp_server_spec({"srv": _Spec()}, "srv")
        assert isinstance(spec, McpStdioServerSpec)
        assert spec.command == "npx"
        assert spec.args == ("-y", "some-server")
        assert spec.env == ()

    def test_url_dict_still_resolves_to_http(self) -> None:
        servers = {"web": {"url": "https://mcp.example.com/rpc"}}
        assert resolve_mcp_server_spec(servers, "web") == "https://mcp.example.com/rpc"

    def test_plain_string_still_resolves_to_http(self) -> None:
        servers = {"web": "https://mcp.example.com/rpc"}
        assert resolve_mcp_server_spec(servers, "web") == "https://mcp.example.com/rpc"

    def test_unknown_server_resolves_to_none(self) -> None:
        assert resolve_mcp_server_spec({}, "nope") is None

    def test_spec_is_hashable_for_caching(self) -> None:
        a = McpStdioServerSpec(command="python", args=("s.py",), env=(("A", "1"),))
        b = McpStdioServerSpec(command="python", args=("s.py",), env=(("A", "1"),))
        assert {a: 1}[b] == 1


class TestStdioTransport:
    @pytest.mark.asyncio
    async def test_list_tools_via_real_subprocess(
        self, stdio_spec: McpStdioServerSpec
    ) -> None:
        async with McpClient(timeout_seconds=10.0) as client:
            tools = await client.list_tools(stdio_spec)
            assert [t.name for t in tools] == ["echo"]
            assert tools[0].description == "Echo text back"
            assert tools[0].parameters["type"] == "object"
            assert tools[0].is_local is False

    @pytest.mark.asyncio
    async def test_call_tool_via_real_subprocess(
        self, stdio_spec: McpStdioServerSpec
    ) -> None:
        async with McpClient(timeout_seconds=10.0) as client:
            result = await client.call_tool(stdio_spec, "echo", {"text": "hi"})
            assert result == {"content": [{"type": "text", "text": "echo:hi"}]}

    @pytest.mark.asyncio
    async def test_tools_list_is_cached_with_ttl(
        self, stdio_spec: McpStdioServerSpec
    ) -> None:
        async with McpClient(timeout_seconds=10.0) as client:
            await client.list_tools(stdio_spec)
            await client.list_tools(stdio_spec)  # served from cache
            result = await client.call_tool(stdio_spec, "list_count", {})
            assert result["content"][0]["text"] == "1"
            # force_refresh bypasses the cache
            await client.list_tools(stdio_spec, force_refresh=True)
            result = await client.call_tool(stdio_spec, "list_count", {})
            assert result["content"][0]["text"] == "2"

    @pytest.mark.asyncio
    async def test_spec_env_is_merged_into_subprocess_env(
        self, server_script: str
    ) -> None:
        spec = McpStdioServerSpec(
            command=sys.executable,
            args=(server_script,),
            env=(("MCP_STDIO_TEST_ENV", "sekret-value"),),
        )
        async with McpClient(timeout_seconds=10.0) as client:
            result = await client.call_tool(spec, "env", {})
            assert result["content"][0]["text"] == "sekret-value"

    @pytest.mark.asyncio
    async def test_jsonrpc_error_maps_to_error_dict(
        self, stdio_spec: McpStdioServerSpec
    ) -> None:
        async with McpClient(timeout_seconds=10.0) as client:
            result = await client.call_tool(stdio_spec, "no_such_tool", {})
            assert "error" in result
            assert "unknown tool" in str(result["error"])

    @pytest.mark.asyncio
    async def test_timeout_returns_error_dict(
        self, stdio_spec: McpStdioServerSpec
    ) -> None:
        client = McpClient(timeout_seconds=10.0)
        try:
            # Warm up the session with a normal call (initialize uses the
            # regular timeout), then hit the never-answering tool.
            await client.call_tool(stdio_spec, "echo", {"text": "warm"})
            client._timeout = 0.5
            for session in client._stdio_sessions.values():
                session._timeout = 0.5
            result = await client.call_tool(stdio_spec, "sleep", {})
            assert "error" in result
            assert "Таймаут" in str(result["error"])
        finally:
            client._timeout = 10.0
            await client.aclose()

    @pytest.mark.asyncio
    async def test_resources_list_and_read(
        self, stdio_spec: McpStdioServerSpec
    ) -> None:
        async with McpClient(timeout_seconds=10.0) as client:
            resources = await client.list_resources(stdio_spec)
            assert [r.uri for r in resources] == ["mem://doc"]
            assert resources[0].mime_type == "text/plain"
            read = await client.read_resource(stdio_spec, "mem://doc")
            assert read["contents"][0]["text"] == "resource-body"

    @pytest.mark.asyncio
    async def test_aclose_terminates_subprocess(
        self, stdio_spec: McpStdioServerSpec
    ) -> None:
        client = McpClient(timeout_seconds=10.0)
        await client.call_tool(stdio_spec, "echo", {"text": "x"})
        session = client._stdio_sessions[stdio_spec]
        proc = session._proc
        assert proc is not None
        assert proc.returncode is None  # still running
        await client.aclose()
        assert proc.returncode is not None  # exited
        assert not client._stdio_sessions

    @pytest.mark.asyncio
    async def test_session_respawns_after_process_death(
        self, stdio_spec: McpStdioServerSpec
    ) -> None:
        async with McpClient(timeout_seconds=10.0) as client:
            await client.call_tool(stdio_spec, "echo", {"text": "a"})
            session = client._stdio_sessions[stdio_spec]
            proc = session._proc
            assert proc is not None
            proc.kill()
            await proc.wait()
            result = await client.call_tool(stdio_spec, "echo", {"text": "b"})
            assert result["content"][0]["text"] == "echo:b"


class TestExecutorStdioIntegration:
    @pytest.mark.asyncio
    async def test_execute_mcp_tool_over_stdio(self, server_script: str) -> None:
        executor = ToolExecutor(
            mcp_servers={"local": {"command": sys.executable, "args": [server_script]}},
            timeout_seconds=10.0,
        )
        try:
            assert executor.has_tool("mcp__local__echo")
            raw = await executor.execute("mcp__local__echo", {"text": "hi"})
            data = json.loads(raw)
            assert data == {"content": [{"type": "text", "text": "echo:hi"}]}
        finally:
            await executor.aclose()

    @pytest.mark.asyncio
    async def test_read_mcp_resource_over_stdio(self, server_script: str) -> None:
        executor = ToolExecutor(
            mcp_servers={"local": {"command": sys.executable, "args": [server_script]}},
            timeout_seconds=10.0,
        )
        try:
            raw = await executor.execute(
                "read_mcp_resource", {"server_id": "local", "uri": "mem://doc"}
            )
            data = json.loads(raw)
            assert data["contents"][0]["text"] == "resource-body"
        finally:
            await executor.aclose()
