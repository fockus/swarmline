"""CLI Agent Runtime - run external CLI agents via subprocess + NDJSON parsing."""

from cognitia.runtime.cli.parser import (
    ClaudeNdjsonParser,
    GenericNdjsonParser,
    NdjsonParser,
)
from cognitia.runtime.cli.runtime import CliAgentRuntime
from cognitia.runtime.cli.types import CliConfig

__all__ = [
    "CliAgentRuntime",
    "CliConfig",
    "ClaudeNdjsonParser",
    "GenericNdjsonParser",
    "NdjsonParser",
]
