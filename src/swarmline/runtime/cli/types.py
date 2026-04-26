"""Domain types for CLI Agent Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

DEFAULT_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
    }
)


class CliPreset(StrEnum):
    """Known CLI agent presets."""

    CLAUDE = "claude"
    PI = "pi"


CliInputFormat = Literal["plain", "pi-rpc"]


@dataclass(frozen=True)
class CliConfig:
    """Configuration for CLI-based agent runtime.

    Describes how to invoke an external CLI agent process
    and how to interpret its output.
    """

    command: list[
        str
    ]  # e.g. ["claude", "--print", "--verbose", "--output-format", "stream-json", "-"]
    output_format: str = "stream-json"
    input_format: CliInputFormat = "plain"
    preset: CliPreset | None = None
    timeout_seconds: float = 300.0
    max_output_bytes: int = 4_000_000
    env: dict[str, str] = field(default_factory=dict)
    inherit_host_env: bool = False
    env_allowlist: frozenset[str] = DEFAULT_ENV_ALLOWLIST

    @classmethod
    def claude(cls, *, timeout_seconds: float = 300.0) -> CliConfig:
        """Build the Claude CLI stream-JSON preset."""
        return cls(
            command=[
                "claude",
                "--print",
                "--verbose",
                "--output-format",
                "stream-json",
                "-",
            ],
            output_format="stream-json",
            input_format="plain",
            preset=CliPreset.CLAUDE,
            timeout_seconds=timeout_seconds,
        )

    @classmethod
    def pi(
        cls,
        *,
        command: str = "pi",
        no_session: bool = True,
        provider: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 300.0,
        env: dict[str, str] | None = None,
        inherit_host_env: bool = False,
    ) -> CliConfig:
        """Build the PI CLI RPC preset."""
        cmd = [command, "--mode", "rpc"]
        if no_session:
            cmd.append("--no-session")
        if provider:
            cmd.extend(["--provider", provider])
        if model:
            cmd.extend(["--model", model])
        return cls(
            command=cmd,
            output_format="pi-rpc",
            input_format="pi-rpc",
            preset=CliPreset.PI,
            timeout_seconds=timeout_seconds,
            env=dict(env or {}),
            inherit_host_env=inherit_host_env,
        )
