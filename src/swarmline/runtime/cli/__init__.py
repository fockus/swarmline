"""CLI Agent Runtime - run external CLI agents via subprocess + NDJSON parsing."""

from swarmline.runtime.cli.parser import (
    ClaudeNdjsonParser,
    GenericNdjsonParser,
    NdjsonParser,
    PiRpcParser,
)
from swarmline.runtime.cli.runtime import CliAgentRuntime
from swarmline.runtime.cli.types import CliConfig, CliPreset

__all__ = [
    "CliAgentRuntime",
    "CliConfig",
    "CliPreset",
    "ClaudeNdjsonParser",
    "GenericNdjsonParser",
    "NdjsonParser",
    "PiRpcParser",
]
