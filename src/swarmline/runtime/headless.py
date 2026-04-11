"""HeadlessRuntime — marker runtime for headless mode (no LLM calls).

Used by the MCP server in headless mode where Swarmline provides
infrastructure (memory, tools, plans) without making LLM calls.
The code agent (Claude Code, Codex, etc.) acts as the brain.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import structlog

from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeEvent,
    ToolSpec,
)

logger = structlog.get_logger(__name__)


class HeadlessRuntime:
    """Runtime that provides no LLM execution.

    All infrastructure features (memory, tools, plans, task queues)
    work normally. Only LLM-dependent operations raise NotImplementedError.
    """

    def __init__(self, config: RuntimeConfig, **kwargs: Any) -> None:
        self._config = config

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Not available in headless mode — use the code agent as LLM."""
        raise NotImplementedError(
            "HeadlessRuntime does not support LLM calls. "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY to enable full mode, "
            "or use the code agent (Claude Code / Codex) as the LLM."
        )
        # Make this a generator (required by AsyncIterator type)
        yield  # pragma: no cover  # noqa: RET503

    def cancel(self) -> None:
        """No-op — nothing to cancel in headless mode."""

    async def cleanup(self) -> None:
        """No-op — nothing to clean up in headless mode."""

    async def __aenter__(self) -> HeadlessRuntime:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.cleanup()
