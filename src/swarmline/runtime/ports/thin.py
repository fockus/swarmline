"""Thin module."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from swarmline.runtime.ports.base import HISTORY_MAX, BaseRuntimePort
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec

logger = logging.getLogger(__name__)

THIN_HISTORY_MAX = HISTORY_MAX
"""Максимальное количество сообщений в in-memory истории ThinRuntime."""


class ThinRuntimePort(BaseRuntimePort):
    """Thin Runtime Port implementation."""

    def __init__(
        self,
        system_prompt: str,
        config: RuntimeConfig | None = None,
        local_tools: dict[str, Any] | None = None,
        summarizer: Any | None = None,
    ) -> None:
        super().__init__(
            system_prompt=system_prompt,
            config=config or RuntimeConfig(runtime_name="thin"),
            history_max=THIN_HISTORY_MAX,
            summarizer=summarizer,
        )
        self._local_tools = local_tools or {}
        self._active_tools = self._build_active_tools(self._local_tools)
        self._runtime: ThinRuntime | None = None

    @staticmethod
    def _build_active_tools(local_tools: dict[str, Any]) -> list[ToolSpec]:
        """Build active tools."""
        active_tools: list[ToolSpec] = []
        for name, tool in local_tools.items():
            tool_definition = getattr(tool, "__tool_definition__", None)
            if tool_definition is not None:
                active_tools.append(tool_definition.to_tool_spec())
                continue

            description = ""
            doc = getattr(tool, "__doc__", None)
            if isinstance(doc, str):
                description = doc.strip().split("\n")[0].strip()

            active_tools.append(
                ToolSpec(
                    name=name,
                    description=description,
                    parameters={},
                    is_local=True,
                )
            )

        return active_tools

    async def connect(self) -> None:
        """Initialize ThinRuntime."""
        self._runtime = ThinRuntime(
            config=self._config,
            local_tools=self._local_tools,
        )
        self._connected = True
        logger.info(
            "ThinRuntimePort подключён: model=%s, base_url=%s",
            self._config.model,
            self._config.base_url or "default",
        )

    async def disconnect(self) -> None:
        """Disconnect."""
        if self._runtime:
            await self._runtime.cleanup()
            self._runtime = None
        await super().disconnect()

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
