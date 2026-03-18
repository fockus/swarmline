"""Domain types for CLI Agent Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CliConfig:
    """Configuration for CLI-based agent runtime.

  Describes how to invoke an external CLI agent process
  and how to interpret its output.
  """

    command: list[str]  # e.g. ["claude", "--print", "--verbose", "--output-format", "stream-json", "-"]
    output_format: str = "stream-json"
    timeout_seconds: float = 300.0
    max_output_bytes: int = 4_000_000
    env: dict[str, str] = field(default_factory=dict)
