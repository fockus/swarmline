"""PI SDK runtime wrapper.

The Python runtime owns Swarmline contracts and launches a small Node bridge
that embeds `@mariozechner/pi-coding-agent` through its public SDK.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from swarmline.runtime.pi_sdk.event_mapper import map_pi_bridge_event
from swarmline.runtime.pi_sdk.types import PiSdkOptions
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
)

ToolExecutor = Callable[..., Any]


class PiSdkRuntime:
    """AgentRuntime implementation backed by PI's TypeScript SDK."""

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        pi_options: PiSdkOptions | None = None,
        tool_executors: dict[str, ToolExecutor] | None = None,
        local_tools: dict[str, ToolExecutor] | None = None,
    ) -> None:
        self._config = config or RuntimeConfig(runtime_name="pi_sdk")
        self._pi_options = pi_options or _options_from_config(self._config)
        self._tool_executors: dict[str, ToolExecutor] = {}
        self._tool_executors.update(local_tools or {})
        self._tool_executors.update(tool_executors or {})
        self._process: asyncio.subprocess.Process | None = None
        self._cancel_requested = False

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Run one Swarmline turn through the PI SDK bridge."""
        effective_config = config or self._config
        request = self._build_run_request(
            messages=messages,
            system_prompt=system_prompt,
            active_tools=active_tools,
            config=effective_config,
        )
        self._cancel_requested = False
        final_seen = False

        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._build_bridge_command(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="dependency_missing",
                    message=(
                        "Node.js is required for runtime='pi_sdk'. Install Node >=20.6 "
                        "and @mariozechner/pi-coding-agent, or use runtime='cli' with CliConfig.pi()."
                    ),
                    recoverable=False,
                )
            )
            return
        except Exception as exc:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=f"Failed to launch PI SDK bridge: {exc}",
                    recoverable=False,
                )
            )
            return

        assert self._process.stdin is not None
        await self._send_jsonl(request)

        try:
            async with asyncio.timeout(self._pi_options.timeout_seconds):
                async for raw_line in self._iter_stdout_lines():
                    data = _loads_json_object(raw_line)
                    if data is None:
                        continue

                    if data.get("type") == "tool_request":
                        async for event in self._handle_tool_request(data):
                            yield event
                        continue

                    event = map_pi_bridge_event(data)
                    if event is None:
                        continue
                    if event.is_final:
                        final_seen = True
                    yield event
        except TimeoutError:
            self._terminate_process()
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="mcp_timeout",
                    message=(
                        "PI SDK bridge timed out after "
                        f"{self._pi_options.timeout_seconds}s"
                    ),
                    recoverable=False,
                )
            )
            return

        if self._process is not None:
            await self._process.wait()
            if self._cancel_requested:
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="cancelled",
                        message="PI SDK run cancelled.",
                        recoverable=False,
                    )
                )
            elif self._process.returncode and self._process.returncode != 0:
                stderr = await self._read_stderr()
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message=f"PI SDK bridge exited with code {self._process.returncode}: {stderr}",
                        recoverable=False,
                    )
                )
            elif not final_seen:
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="bad_model_output",
                        message="PI SDK bridge exited without a final event.",
                        recoverable=False,
                    )
                )

    def cancel(self) -> None:
        """Request cooperative cancellation of the active PI bridge."""
        self._cancel_requested = True
        if self._process and self._process.stdin and self._process.returncode is None:
            self._write_jsonl({"type": "cancel"})
        self._terminate_process()

    async def cleanup(self) -> None:
        """Release bridge process resources."""
        self._terminate_process()
        if self._process and self._process.returncode is None:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
        self._cancel_requested = False

    async def __aenter__(self) -> PiSdkRuntime:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.cleanup()

    def _build_bridge_command(self) -> tuple[str, ...]:
        """Return the command used to launch the packaged Node bridge."""
        if self._pi_options.bridge_command:
            return self._pi_options.bridge_command
        bridge = Path(__file__).with_name("bridge.mjs")
        return ("node", str(bridge))

    def _build_run_request(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
    ) -> dict[str, Any]:
        """Serialize one run request for the Node bridge."""
        effective_config = config or self._config
        options = self._pi_options
        return {
            "type": "run",
            "runtime": {
                "runtime_name": effective_config.runtime_name,
                "model": effective_config.model,
                "base_url": effective_config.base_url,
                "request_options": (
                    effective_config.request_options.__dict__
                    if effective_config.request_options is not None
                    else None
                ),
            },
            "options": {
                "toolset": options.toolset,
                "coding_profile": options.coding_profile,
                "cwd": options.cwd,
                "agent_dir": options.agent_dir,
                "auth_file": options.auth_file,
                "session_mode": options.session_mode,
                "package_name": options.package_name,
                "provider": options.provider,
                "model_id": options.model_id,
                "thinking_level": options.thinking_level,
            },
            "system_prompt": system_prompt,
            "messages": [message.to_dict() for message in messages],
            "tools": [
                spec.to_dict()
                for spec in active_tools
                if spec.is_local and spec.name in self._tool_executors
            ],
        }

    async def _iter_stdout_lines(self) -> AsyncIterator[str]:
        if self._process is None or self._process.stdout is None:
            return
        async for raw_line in self._process.stdout:
            yield raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

    async def _handle_tool_request(self, data: dict[str, Any]) -> AsyncIterator[RuntimeEvent]:
        request_id = str(data.get("id", ""))
        name = str(data.get("name", ""))
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        yield RuntimeEvent.tool_call_started(
            name=name,
            args=args,
            correlation_id=request_id,
        )

        ok = True
        try:
            result = await self._execute_tool(name, args)
        except Exception as exc:
            ok = False
            result = f"{type(exc).__name__}: {exc}"

        await self._send_jsonl(
            {
                "type": "tool_response",
                "id": request_id,
                "ok": ok,
                "result": result,
            }
        )
        yield RuntimeEvent.tool_call_finished(
            name=name,
            correlation_id=request_id,
            ok=ok,
            result_summary=str(result),
        )

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> str:
        executor = self._tool_executors.get(name)
        if executor is None:
            raise KeyError(f"Unknown local tool: {name}")
        result = executor(**args)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    def _write_jsonl(self, payload: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            return
        self._process.stdin.write(
            (json.dumps(payload, ensure_ascii=False, default=str) + "\n").encode()
        )

    async def _send_jsonl(self, payload: dict[str, Any]) -> None:
        self._write_jsonl(payload)
        if self._process is not None and self._process.stdin is not None:
            await self._process.stdin.drain()

    def _terminate_process(self) -> None:
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass

    async def _read_stderr(self) -> str:
        if self._process is None or self._process.stderr is None:
            return ""
        data = await self._process.stderr.read()
        return data.decode("utf-8", errors="replace")


def _loads_json_object(line: str) -> dict[str, Any] | None:
    if not line.strip():
        return None
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _options_from_config(config: RuntimeConfig) -> PiSdkOptions:
    raw = config.native_config.get("pi_sdk") if isinstance(config.native_config, dict) else None
    if isinstance(raw, PiSdkOptions):
        return raw
    if isinstance(raw, dict):
        return PiSdkOptions(**raw)
    return PiSdkOptions()
