"""Deepagents module."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from cognitia.runtime.ports.base import HISTORY_MAX, BaseRuntimePort
from cognitia.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cognitia.runtime.deepagents import DeepAgentsRuntime


class DeepAgentsRuntimePort(BaseRuntimePort):
    """Deep Agents Runtime Port implementation."""

    def __init__(
        self,
        system_prompt: str,
        config: RuntimeConfig | None = None,
        active_tools: list[ToolSpec] | None = None,
        tool_executors: dict[str, Callable] | None = None,
        summarizer: Any | None = None,
        memory_sources: list[str] | None = None,
    ) -> None:
        from dataclasses import replace

        effective_config = config or RuntimeConfig(runtime_name="deepagents")
        prompt_memory_sources = memory_sources


        if memory_sources and effective_config.is_native_mode:
            native = {**effective_config.native_config, "memory": list(memory_sources)}
            prompt_memory_sources = None
            # Auto-backend: memory without backend -> FilesystemBackend(root_dir=".")
            if "backend" not in native:
                try:
                    from deepagents.backends.filesystem import (  # type: ignore[import-not-found]
                        FilesystemBackend,
                    )

                    native["backend"] = FilesystemBackend(root_dir=".", virtual_mode=False)
                except ImportError:
                    logger.warning("deepagents FilesystemBackend unavailable, auto-backend skipped")
            effective_config = replace(effective_config, native_config=native)

        super().__init__(
            system_prompt=system_prompt,
            config=effective_config,
            history_max=HISTORY_MAX,
            summarizer=summarizer,
            memory_sources=prompt_memory_sources,
        )
        self._active_tools = active_tools or []
        self._tool_executors = tool_executors or {}
        self._runtime: DeepAgentsRuntime | None = None

    async def connect(self) -> None:
        """Initialize DeepAgentsRuntime."""
        try:
            from cognitia.runtime.deepagents import DeepAgentsRuntime
        except ImportError as exc:
            raise RuntimeError(
                "DeepAgents runtime недоступен: установите optional dependency "
                "`cognitia[deepagents]`."
            ) from exc
        self._runtime = DeepAgentsRuntime(
            config=self._config,
            tool_executors=self._tool_executors,
        )
        self._connected = True
        logger.info(
            "DeepAgentsRuntimePort подключён: model=%s, tools=%d",
            self._config.model,
            len(self._active_tools),
        )

    async def disconnect(self) -> None:
        """Disconnect."""
        if self._runtime:
            await self._runtime.cleanup()
            self._runtime = None
        await super().disconnect()

    def _is_native_mode(self) -> bool:
        """Is native mode."""
        return self._config.is_native_mode

    async def _maybe_summarize(self) -> None:
        """Noop for native mode - upstream handles compaction."""
        if self._is_native_mode():
            return
        await super()._maybe_summarize()

    async def _run_runtime(
        self,
        messages: list[Message],
        system_prompt: str,
    ) -> AsyncIterator[RuntimeEvent]:
        """Run runtime."""
        if not self._runtime:
            return
        async for event in self._runtime.run(
            messages=messages,
            system_prompt=system_prompt,
            active_tools=self._active_tools,
        ):
            yield event
