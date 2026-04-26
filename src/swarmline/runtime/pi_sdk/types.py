"""Types for the PI SDK runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PiToolset = Literal["none", "readonly", "coding"]
PiSessionMode = Literal["memory", "persisted"]


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
