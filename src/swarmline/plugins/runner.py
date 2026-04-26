"""PluginRunner protocol + SubprocessPluginRunner implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, runtime_checkable

from swarmline.plugins.runner_types import PluginHandle, PluginManifest, PluginState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class PluginRunner(Protocol):
    """Process-isolated plugin execution. ISP: 4 methods."""

    async def start(self, manifest: PluginManifest) -> PluginHandle: ...
    async def call(
        self,
        handle: PluginHandle,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any: ...
    async def stop(self, handle: PluginHandle) -> bool: ...
    async def health(self, handle: PluginHandle) -> PluginState: ...


# ---------------------------------------------------------------------------
# Internal mutable state
# ---------------------------------------------------------------------------


@dataclass
class _PluginProcess:
    """Mutable bookkeeping for a running plugin subprocess."""

    manifest: PluginManifest
    handle: PluginHandle
    process: asyncio.subprocess.Process | None = None
    restart_count: int = 0
    rpc_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


class SubprocessPluginRunner:
    """Spawn plugins as subprocesses, communicate via JSON-RPC over stdio."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        self._processes: dict[str, _PluginProcess] = {}
        self._env = env

    # -- public API --------------------------------------------------------

    async def start(self, manifest: PluginManifest) -> PluginHandle:
        """Launch the plugin subprocess and return a handle."""
        plugin_id = uuid.uuid4().hex[:12]
        process = await self._launch(manifest)

        # Brief wait to detect immediate crash
        await asyncio.sleep(0.1)
        if process.returncode is not None:
            raise RuntimeError(
                f"Plugin {manifest.name!r} crashed immediately "
                f"(exit code {process.returncode})"
            )

        handle = PluginHandle(
            plugin_id=plugin_id,
            name=manifest.name,
            pid=process.pid,
            state=PluginState.RUNNING,
            restart_count=0,
            started_at=time.time(),
        )
        pp = _PluginProcess(
            manifest=manifest,
            handle=handle,
            process=process,
            restart_count=0,
        )
        self._processes[plugin_id] = pp
        logger.info(
            "plugin.started name=%s pid=%s id=%s", manifest.name, process.pid, plugin_id
        )
        return handle

    async def call(
        self,
        handle: PluginHandle,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send a JSON-RPC call and return the result."""
        pp = self._processes.get(handle.plugin_id)
        if pp is None:
            raise KeyError(f"Unknown plugin: {handle.plugin_id}")

        # Auto-restart if crashed
        if pp.process is None or pp.process.returncode is not None:
            await self._auto_restart(pp)

        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": uuid.uuid4().hex[:8],
        }
        return await self._send_rpc(pp, request)

    async def stop(self, handle: PluginHandle) -> bool:
        """Gracefully stop the plugin subprocess."""
        pp = self._processes.get(handle.plugin_id)
        if pp is None:
            return False

        process = pp.process
        if process is not None and process.returncode is None:
            # Try graceful shutdown via JSON-RPC
            shutdown_req = (
                json.dumps(
                    {"jsonrpc": "2.0", "method": "__shutdown__", "id": "shutdown"}
                )
                + "\n"
            )
            try:
                async with pp.rpc_lock:
                    assert process.stdin is not None
                    process.stdin.write(shutdown_req.encode())
                    await process.stdin.drain()
                    await asyncio.wait_for(process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, OSError, BrokenPipeError):
                # Graceful failed -- escalate
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

        del self._processes[handle.plugin_id]
        logger.info("plugin.stopped name=%s id=%s", handle.name, handle.plugin_id)
        return True

    async def health(self, handle: PluginHandle) -> PluginState:
        """Probe the plugin process health via __ping__."""
        pp = self._processes.get(handle.plugin_id)
        if pp is None:
            return PluginState.STOPPED

        process = pp.process
        if process is None or process.returncode is not None:
            return PluginState.CRASHED

        ping_req = {
            "jsonrpc": "2.0",
            "method": "__ping__",
            "id": "ping",
        }
        try:
            await self._send_rpc(pp, ping_req, timeout=2.0)
            return PluginState.RUNNING
        except Exception:
            return PluginState.CRASHED

    # -- internal helpers --------------------------------------------------

    async def _launch(self, manifest: PluginManifest) -> asyncio.subprocess.Process:
        """Create the subprocess for the worker shim."""
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "swarmline.plugins._worker_shim",
            manifest.entry_point,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )

    async def _send_rpc(
        self,
        pp: _PluginProcess,
        request: dict[str, Any],
        timeout: float | None = None,
    ) -> Any:
        """Write a JSON-RPC request, read response, return result or raise."""
        process = pp.process
        assert process is not None
        assert process.stdin is not None
        assert process.stdout is not None

        effective_timeout = timeout or pp.manifest.timeout_seconds
        async with pp.rpc_lock:
            line = json.dumps(request) + "\n"
            process.stdin.write(line.encode())
            await process.stdin.drain()

            raw = await asyncio.wait_for(
                process.stdout.readline(),
                timeout=effective_timeout,
            )
        if not raw:
            raise RuntimeError("Plugin process closed stdout unexpectedly")

        response = json.loads(raw.decode())
        if "error" in response:
            err = response["error"]
            raise RuntimeError(
                f"Plugin RPC error [{err.get('code', '?')}]: {err.get('message', 'unknown')}"
            )
        return response.get("result")

    async def _auto_restart(self, pp: _PluginProcess) -> None:
        """Restart a crashed plugin with exponential backoff."""
        if pp.restart_count >= pp.manifest.max_restarts:
            raise RuntimeError(
                f"Plugin {pp.manifest.name!r} exceeded max restarts "
                f"({pp.manifest.max_restarts})"
            )

        backoff = pp.manifest.restart_backoff_base**pp.restart_count
        logger.warning(
            "plugin.restarting name=%s attempt=%d backoff=%.1fs",
            pp.manifest.name,
            pp.restart_count + 1,
            backoff,
        )
        await asyncio.sleep(backoff)

        process = await self._launch(pp.manifest)
        await asyncio.sleep(0.1)
        if process.returncode is not None:
            pp.restart_count += 1
            raise RuntimeError(
                f"Plugin {pp.manifest.name!r} crashed on restart "
                f"(attempt {pp.restart_count})"
            )

        pp.process = process
        pp.restart_count += 1
        pp.handle = replace(
            pp.handle,
            pid=process.pid,
            state=PluginState.RUNNING,
            restart_count=pp.restart_count,
            started_at=time.time(),
        )
