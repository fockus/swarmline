"""Types for the PI SDK runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from swarmline.runtime.cli.types import DEFAULT_ENV_ALLOWLIST

PiToolset = Literal["none", "readonly", "coding"]
PiSessionMode = Literal["memory", "persisted"]

# Default env allowlist for the pi_sdk Node bridge. Extends the generic CLI
# defaults with Node + provider auth keys that pi-coding-agent expects.
# See plans/2026-04-27_fix_security-audit.md Stage 2.
DEFAULT_PI_SDK_ENV_ALLOWLIST: frozenset[str] = DEFAULT_ENV_ALLOWLIST | {
    "NODE_PATH",
    "NODE_ENV",
    "NODE_OPTIONS",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
}


@dataclass(frozen=True)
class PiSdkOptions:
    """Configuration for the Node bridge that embeds PI's TypeScript SDK."""

    toolset: PiToolset = "none"
    coding_profile: str | None = None
    cwd: str | None = None
    agent_dir: str | None = None
    auth_file: str | None = None
    session_mode: PiSessionMode = "memory"
    bridge_command: tuple[str, ...] = ()
    package_name: str = "@mariozechner/pi-coding-agent"
    provider: str | None = None
    model_id: str | None = None
    thinking_level: str | None = None
    timeout_seconds: float = 300.0
    inherit_host_env: bool = False
    env_allowlist: frozenset[str] = DEFAULT_PI_SDK_ENV_ALLOWLIST
    env: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.toolset not in {"none", "readonly", "coding"}:
            raise ValueError(
                "PiSdkOptions.toolset must be one of: none, readonly, coding"
            )
        if self.session_mode not in {"memory", "persisted"}:
            raise ValueError(
                "PiSdkOptions.session_mode must be one of: memory, persisted"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("PiSdkOptions.timeout_seconds must be positive")
