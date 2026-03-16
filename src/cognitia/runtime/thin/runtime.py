"""ThinRuntime -- собственный тонкий агентный loop.

3 режима: conversational | react | planner-lite.
Bounded loops, typed errors, streaming RuntimeEvent.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from cognitia.runtime.thin.builtin_tools import create_thin_builtin_tools
from cognitia.runtime.thin.executor import ToolExecutor
from cognitia.runtime.thin.llm_client import default_llm_call
from cognitia.runtime.thin.modes import detect_mode
from cognitia.runtime.thin.strategies import (
    run_conversational,
    run_planner,
    run_react,
)
from cognitia.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
)


class ThinRuntime:
    """Собственный тонкий агентный loop.

    Режимы:
    - conversational: single LLM call -> final
    - react: loop (LLM -> tool_call | final)
    - planner: plan JSON -> step execution -> final assembly

    Args:
        config: Конфигурация runtime (budgets, model).
        llm_call: Callable для вызова LLM (для тестирования).
                  Сигнатура: async (messages, system_prompt) -> str
        local_tools: Маппинг tool_name -> callable.
    """

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        llm_call: Callable[..., Any] | None = None,
        local_tools: dict[str, Callable[..., Any]] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        react_patterns: list[re.Pattern[str]] | None = None,
        planner_patterns: list[re.Pattern[str]] | None = None,
        sandbox: Any | None = None,
    ) -> None:
        self._config = config or RuntimeConfig(runtime_name="thin")
        self._llm_call = llm_call or self._make_default_llm_call()
        self._react_patterns = react_patterns
        self._planner_patterns = planner_patterns

        # Merge user local_tools with sandbox built-in executors
        merged_local_tools = dict(local_tools or {})
        _builtin_specs, builtin_executors = create_thin_builtin_tools(sandbox)
        for name, executor in builtin_executors.items():
            # User tools take priority over built-ins
            if name not in merged_local_tools:
                merged_local_tools[name] = executor

        self._executor = ToolExecutor(
            local_tools=merged_local_tools,
            mcp_servers=mcp_servers,
        )

    def _make_default_llm_call(self) -> Callable[..., Any]:
        """Создать default LLM call, привязанный к self._config."""
        config = self._config

        async def _call(
            messages: list[dict[str, str]],
            system_prompt: str,
            **kwargs: Any,
        ) -> str:
            return await default_llm_call(config, messages, system_prompt, **kwargs)

        return _call

    async def run(
        self,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        config: RuntimeConfig | None = None,
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Выполнить один turn.

        1. Определить mode (conversational/react/planner)
        2. Запустить соответствующий loop
        3. Emit RuntimeEvent (стрим)
        """
        effective_config = config or self._config
        start_time = time.monotonic()

        # Определяем mode
        user_text = self._extract_last_user_text(messages)
        mode = detect_mode(
            user_text,
            mode_hint,
            react_patterns=self._react_patterns,
            planner_patterns=self._planner_patterns,
        )

        yield RuntimeEvent.status(f"Режим: {mode}")

        try:
            if mode == "conversational":
                async for event in run_conversational(
                    self._llm_call,
                    messages,
                    system_prompt,
                    effective_config,
                    start_time,
                ):
                    yield event

            elif mode == "react":
                async for event in run_react(
                    self._llm_call,
                    self._executor,
                    messages,
                    system_prompt,
                    active_tools,
                    effective_config,
                    start_time,
                ):
                    yield event

            elif mode == "planner":
                async for event in run_planner(
                    self._llm_call,
                    self._executor,
                    messages,
                    system_prompt,
                    active_tools,
                    effective_config,
                    start_time,
                ):
                    yield event

        except Exception as e:
            yield RuntimeEvent.error(
                RuntimeErrorData(
                    kind="runtime_crash",
                    message=f"ThinRuntime crash: {e}",
                    recoverable=False,
                )
            )

    @staticmethod
    def _extract_last_user_text(messages: list[Message]) -> str:
        """Извлечь текст последнего user message."""
        for msg in reversed(messages):
            if msg.role == "user" and msg.content:
                return msg.content
        return ""

    async def cleanup(self) -> None:
        """Нечего очищать -- stateless."""
