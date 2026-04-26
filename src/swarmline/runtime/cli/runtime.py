"""CLI Agent Runtime -- subprocess-based runtime for external CLI agents.

Runs an external CLI process, feeds it prompt via stdin, and parses
NDJSON output from stdout into RuntimeEvent stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from swarmline.runtime._subprocess_env import build_subprocess_env
from swarmline.runtime.cli.parser import (
    ClaudeNdjsonParser,
    GenericNdjsonParser,
    NdjsonParser,
    PiRpcParser,
)
from swarmline.runtime.cli.types import CliConfig
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
)

logger = logging.getLogger(__name__)


def _build_subprocess_env(cli_config: CliConfig) -> dict[str, str]:
    """Build subprocess env via shared helper (Stage 2 of security audit DRY).

    Thin wrapper retained for callers that still depend on the CliConfig-typed
    signature. New code should call ``build_subprocess_env`` directly.
    """
    return build_subprocess_env(
        inherit_host_env=cli_config.inherit_host_env,
        env_allowlist=cli_config.env_allowlist,
        overrides=cli_config.env,
    )


def _build_stdin_payload(messages: list[Message], system_prompt: str) -> str:
    """Serialize system instructions and conversation for CLI stdin."""
    sections: list[str] = []
    if system_prompt.strip():
        sections.append(f"System instructions:\n{system_prompt}")

    conversation = "\n".join(f"{m.role}: {m.content}" for m in messages)
    sections.append(f"Conversation:\n{conversation}")
    return "\n\n".join(sections)


def _build_cli_input_payload(
    *,
    cli_config: CliConfig,
    messages: list[Message],
    system_prompt: str,
) -> str:
    """Serialize runtime input according to the selected CLI protocol."""
    prompt = _build_stdin_payload(messages, system_prompt)
    if cli_config.input_format == "pi-rpc":
        return (
            json.dumps({"type": "prompt", "message": prompt}, ensure_ascii=False) + "\n"
        )
    return prompt


def _is_claude_command(command: list[str]) -> bool:
    """Is claude command."""
    if not command:
        return False
    return os.path.basename(command[0]) == "claude"


def _is_pi_command(command: list[str]) -> bool:
    """Return True for PI CLI commands."""
    if not command:
        return False
    return os.path.basename(command[0]) == "pi"


def _normalize_claude_command(command: list[str], output_format: str) -> list[str]:
    """Normalize claude command."""
    if not _is_claude_command(command):
        return list(command)

    normalized = [
        "--output-format" if token == "--output" else token for token in command
    ]

    prompt_placeholder = normalized[-1] == "-" if normalized else False
    core = normalized[:-1] if prompt_placeholder else normalized[:]

    if "--print" not in core and "-p" not in core:
        core.append("--print")

    if "--output-format" not in core:
        core.extend(["--output-format", output_format])

    if output_format == "stream-json" and "--verbose" not in core and "-v" not in core:
        core.append("--verbose")

    if prompt_placeholder:
        core.append("-")
    return core


class CliAgentRuntime:
    """Run external CLI agents via subprocess + NDJSON parsing.

    Implements AgentRuntime protocol. Parser is auto-selected based on
    the command name (``Claude`` -> ClaudeNdJSONParser, else Generic).
    """

    def __init__(
        self,
        config: RuntimeConfig,
        cli_config: CliConfig | None = None,
        parser: NdjsonParser | None = None,
    ) -> None:
        self._config = config
        self._cli_config = cli_config or CliConfig(
            command=[
                "claude",
                "--print",
                "--verbose",
                "--output-format",
                "stream-json",
                "-",
            ]
        )
        if parser is not None:
            self._parser = parser
        elif _is_claude_command(self._cli_config.command):
            self._parser = ClaudeNdjsonParser()
        elif self._cli_config.output_format == "pi-rpc" or _is_pi_command(
            self._cli_config.command
        ):
            self._parser = PiRpcParser()
        else:
            self._parser = GenericNdjsonParser()
        self._process: asyncio.subprocess.Process | None = None
        self._cancel_requested = False

    async def run(  # noqa: C901
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Execute CLI agent and yield RuntimeEvents from its NDJSON output."""
        prompt = _build_cli_input_payload(
            cli_config=self._cli_config,
            messages=messages,
            system_prompt=system_prompt,
        )
        cmd = _normalize_claude_command(
            self._cli_config.command,
            self._cli_config.output_format,
        )
        env = _build_subprocess_env(self._cli_config)

        total_bytes = 0
        max_bytes = self._cli_config.max_output_bytes
        timeout = self._cli_config.timeout_seconds
        final_seen = False
        self._cancel_requested = False

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            if self._process.stdin:
                self._process.stdin.write(prompt.encode())
                await self._process.stdin.drain()
                self._process.stdin.close()

            async def _read_and_parse() -> AsyncIterator[RuntimeEvent]:
                nonlocal total_bytes, final_seen
                if not self._process or not self._process.stdout:
                    return
                async for raw_line in self._process.stdout:
                    total_bytes += len(raw_line)
                    if total_bytes > max_bytes:
                        self._terminate_process()
                        yield RuntimeEvent.error(
                            RuntimeErrorData(
                                kind="budget_exceeded",
                                message=f"Output exceeded {max_bytes} bytes",
                            )
                        )
                        return
                    line = raw_line.decode("utf-8", errors="replace").rstrip()
                    if not line:
                        continue
                    event = self._parser.parse_line(line)
                    if event is not None:
                        if event.is_final:
                            final_seen = True
                        yield event

            try:
                async with asyncio.timeout(timeout):
                    async for event in _read_and_parse():
                        yield event
            except TimeoutError:
                self._terminate_process()
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="mcp_timeout",
                        message=f"CLI process timed out after {timeout}s",
                        recoverable=False,
                    )
                )
                return

            await self._process.wait()
            if self._cancel_requested:
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="cancelled",
                        message="CLI process cancelled",
                        recoverable=False,
                    )
                )
            elif self._process.returncode and self._process.returncode != 0:
                stderr_data = b""
                if self._process.stderr:
                    stderr_data = await self._process.stderr.read()
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message=(
                            f"Process exited with code {self._process.returncode}: "
                            f"{stderr_data.decode(errors='replace')}"
                        ),
                    )
                )
            elif not final_seen:
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="bad_model_output",
                        message="CLI process exited without a final NDJSON event",
                    )
                )

        except Exception:
            logger.exception("CliAgentRuntime.run() failed")
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash", message="Unexpected error in CLI runtime"
                )
            )

    def cancel(self) -> None:
        """Request cooperative cancellation of the current subprocess."""
        if self._process and self._process.returncode is None:
            self._cancel_requested = True
        self._terminate_process()

    async def cleanup(self) -> None:
        """Release subprocess resources."""
        self._terminate_process()
        if self._process and self._process.returncode is None:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
        self._cancel_requested = False

    def _terminate_process(self) -> None:
        """Send SIGTERM to subprocess if still running."""
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass

    async def __aenter__(self) -> CliAgentRuntime:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.cleanup()
