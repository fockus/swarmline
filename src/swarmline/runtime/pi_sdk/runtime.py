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

from swarmline.runtime._subprocess_env import build_subprocess_env
from swarmline.runtime.cost import CostBudget
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
                env=build_subprocess_env(
                    inherit_host_env=self._pi_options.inherit_host_env,
                    env_allowlist=self._pi_options.env_allowlist,
                    overrides=_build_env_overrides(effective_config, self._pi_options),
                ),
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
                        # I-098a (finding 2): cost_budget was translated into
                        # RuntimeConfig but never enforced. PI only reports
                        # total_cost_usd on the final event, so -- unlike
                        # thin's per-call check (thin/runtime.py:~235/651) --
                        # enforcement here necessarily fires post-hoc, at run
                        # end, once the actual cost is known.
                        budget_error = _budget_exceeded_event(
                            effective_config.cost_budget, event
                        )
                        if budget_error is not None:
                            yield budget_error
                            # Suppress the final event but keep draining to
                            # EOF so the normal post-loop wait() still reaps
                            # the bridge process (no zombie on early exit).
                            continue
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

    CANCEL_GRACE_SECONDS = 1.5

    def cancel(self) -> None:
        """Request cooperative cancellation of the active PI bridge.

        Sends the native ``{"type": "cancel"}`` (bridge calls
        ``session.abort()``) and gives the bridge a short grace period before
        SIGTERM so the native interrupt actually has time to run; without a
        running loop the process is terminated immediately.
        """
        self._cancel_requested = True
        sent_native_cancel = False
        if self._process and self._process.stdin and self._process.returncode is None:
            self._write_jsonl({"type": "cancel"})
            sent_native_cancel = True
        if not sent_native_cancel:
            self._terminate_process()
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._terminate_process()
            return
        loop.call_later(self.CANCEL_GRACE_SECONDS, self._terminate_process)

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
        session_file = options.resume_session_file or _optional_extra_str(
            effective_config, "pi_session_file"
        )
        if session_file and options.session_mode != "persisted":
            raise ValueError(
                "PI resume requires session_mode='persisted': "
                "resume_session_file/pi_session_file is ignored by the bridge "
                "in 'memory' mode. Set PiSdkOptions(session_mode='persisted')."
            )
        resume_fallback = options.resume_fallback or bool(
            effective_config.extra.get("pi_resume_fallback", False)
        )
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
                "session_file": session_file,
                "resume_fallback": resume_fallback,
                "project_instructions": bool(
                    effective_config.extra.get("project_instructions", True)
                ),
                "package_name": options.package_name,
                "provider": options.provider,
                "model_id": options.model_id,
                "thinking_level": (
                    options.thinking_level
                    if options.thinking_level is not None
                    else _thinking_level_from_runtime_config(effective_config)
                ),
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

    async def _handle_tool_request(
        self, data: dict[str, Any]
    ) -> AsyncIterator[RuntimeEvent]:
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
            result = await self._execute_tool(name, args)  # ty: ignore[invalid-argument-type]  # args narrowed by isinstance dict check above
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


def _optional_extra_str(config: RuntimeConfig, key: str) -> str | None:
    """Return a non-empty string value from config.extra, else None."""
    value = config.extra.get(key) if isinstance(config.extra, dict) else None
    if isinstance(value, str) and value:
        return value
    return None


def _budget_exceeded_event(
    cost_budget: CostBudget | None, final_event: RuntimeEvent
) -> RuntimeEvent | None:
    """Enforce RuntimeConfig.cost_budget against a bridge "final" event.

    PI reports cost only once, on the final event (no per-call usage
    stream), so -- unlike thin's pre/post-call CostTracker check
    (thin/runtime.py:~235/651, thin/runtime_support.py budget_exceeded_event)
    -- this necessarily runs post-hoc at run end.

    Returns a "budget_exceeded" error RuntimeEvent (same ``kind`` as thin's)
    that must be yielded INSTEAD of ``final_event`` when
    ``action_on_exceed == "error"`` and the reported cost exceeds the cap;
    returns None (final_event passes through unchanged) when no budget is
    configured, the cap is not exceeded, cost was not reported, or
    ``action_on_exceed == "warn"``.
    """
    if cost_budget is None or cost_budget.max_cost_usd is None:
        return None
    total_cost_usd = final_event.data.get("total_cost_usd")
    if not isinstance(total_cost_usd, int | float):
        return None
    if total_cost_usd <= cost_budget.max_cost_usd:
        return None
    if cost_budget.action_on_exceed != "error":
        # "warn": no enforcement action here, final_event passes through.
        return None
    return RuntimeEvent.error(
        RuntimeErrorData(
            kind="budget_exceeded",
            message=(
                "Cost budget exceeded: "
                f"${total_cost_usd:.4f} spent, cap ${cost_budget.max_cost_usd:.4f}"
            ),
            recoverable=False,
        )
    )


def _thinking_level_from_runtime_config(config: RuntimeConfig) -> str | None:
    """Derive PiSdkOptions.thinking_level from RuntimeConfig.thinking (I-098a).

    Only consulted when PiSdkOptions.thinking_level itself is not explicitly
    set -- an explicit option always wins over this derivation.

    Mapping (RuntimeConfig.thinking.budget_tokens -> thinking_level):
      < 4_000   -> "low"
      < 16_000  -> "medium"
      otherwise -> "high"
    RuntimeConfig.thinking is None (disabled / not requested) -> None.
    """
    thinking = config.thinking
    if thinking is None:
        return None
    if thinking.budget_tokens < 4_000:
        return "low"
    if thinking.budget_tokens < 16_000:
        return "medium"
    return "high"


def _build_env_overrides(
    config: RuntimeConfig, options: PiSdkOptions
) -> dict[str, str]:
    """Merge portable env forwarding (RuntimeConfig.extra["env"], from
    AgentConfig.env -- I-098a) under explicit PiSdkOptions.env, which always
    wins for the same key (documented fallback precedence, mirroring
    resume_session_file/pi_session_file)."""
    config_env = config.extra.get("env") if isinstance(config.extra, dict) else None
    merged: dict[str, str] = dict(config_env) if isinstance(config_env, dict) else {}
    merged.update(options.env)
    return merged


def _options_from_config(config: RuntimeConfig) -> PiSdkOptions:
    raw = (
        config.native_config.get("pi_sdk")
        if isinstance(config.native_config, dict)
        else None
    )
    if isinstance(raw, PiSdkOptions):
        return raw
    if isinstance(raw, dict):
        return PiSdkOptions(**raw)
    return PiSdkOptions()
