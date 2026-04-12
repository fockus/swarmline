"""CodingProfileConfig — opt-in coding-agent profile for ThinRuntime.

Frozen dataclass that declares coding profile parameters.
When enabled on AgentConfig, ThinRuntime gains the canonical coding
tool surface (read/write/edit/multi_edit/bash/ls/glob/grep) with
matching policy scope.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodingProfileConfig:
    """Opt-in coding-agent profile configuration.

    Attributes:
        enabled: Master switch — when True, coding tools are injected
                 and policy is scoped to the coding tool set.
        allow_host_execution: Whether the coding sandbox permits host
                              commands (bash). Set to False for read-only profiles.
    """

    enabled: bool = True
    allow_host_execution: bool = True
