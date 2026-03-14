"""RuntimeFactory — фабрика runtime по конфигурации.

Приоритет выбора: runtime_override > config.runtime_name > env COGNITIA_RUNTIME > default.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

from cognitia.runtime.base import AgentRuntime
from cognitia.runtime.capabilities import (
    CapabilityRequirements,
    RuntimeCapabilities,
    get_runtime_capabilities,
)
from cognitia.runtime.types import (
    VALID_RUNTIME_NAMES,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
)


class RuntimeFactory:
    """Фабрика для создания AgentRuntime по конфигурации.

    Поддерживаемые runtime:
    - claude_sdk: ClaudeCodeRuntime (обёртка claude-agent-sdk)
    - deepagents: DeepAgentsRuntime (LangChain, optional dep)
    - thin: ThinRuntime (собственный loop)

    Использование:
        factory = RuntimeFactory()
        runtime = factory.create(config=RuntimeConfig(runtime_name="thin"))
    """

    def resolve_runtime_name(
        self,
        config: RuntimeConfig | None = None,
        runtime_override: str | None = None,
    ) -> str:
        """Определить имя runtime по приоритету.

        Приоритет: runtime_override > config.runtime_name > env > default.
        """
        # 1. Явный override (CLI flag, per-request)
        if runtime_override and runtime_override in VALID_RUNTIME_NAMES:
            return runtime_override

        # 2. Из конфигурации
        if config and config.runtime_name in VALID_RUNTIME_NAMES:
            return config.runtime_name

        # 3. Из переменной окружения
        env_runtime = os.environ.get("COGNITIA_RUNTIME", "").strip().lower()
        if env_runtime in VALID_RUNTIME_NAMES:
            return env_runtime

        # 4. Default
        return "claude_sdk"

    def get_capabilities(
        self,
        config: RuntimeConfig | None = None,
        runtime_override: str | None = None,
    ) -> RuntimeCapabilities:
        """Получить capability descriptor без запуска runtime."""
        name = self.resolve_runtime_name(config, runtime_override)
        return get_runtime_capabilities(name)

    def validate_capabilities(
        self,
        config: RuntimeConfig | None = None,
        runtime_override: str | None = None,
        required_capabilities: CapabilityRequirements | None = None,
    ) -> RuntimeErrorData | None:
        """Проверить, удовлетворяет ли выбранный runtime требуемым capability."""
        caps = self.get_capabilities(config=config, runtime_override=runtime_override)
        requirements = required_capabilities
        if requirements is None and config is not None:
            requirements = config.required_capabilities

        missing = caps.missing(requirements)
        if not missing:
            return None

        return RuntimeErrorData(
            kind="capability_unsupported",
            message=(
                f"Runtime '{caps.runtime_name}' не поддерживает требуемые capabilities: "
                f"{', '.join(missing)}"
            ),
            recoverable=False,
            details={
                "runtime_name": caps.runtime_name,
                "missing": list(missing),
            },
        )

    def create(
        self,
        config: RuntimeConfig | None = None,
        runtime_override: str | None = None,
        **kwargs: Any,
    ) -> AgentRuntime:
        """Создать runtime по конфигурации.

        Args:
            config: Конфигурация runtime.
            runtime_override: Явный override имени runtime.
            **kwargs: Дополнительные параметры для конструктора runtime.

        Returns:
            Экземпляр AgentRuntime.

        Raises:
            ValueError: Неизвестный runtime.
        """
        name = self.resolve_runtime_name(config, runtime_override)
        effective_config = config or RuntimeConfig(runtime_name=name)

        # RuntimeConfig.__post_init__ валидирует capabilities для config.runtime_name.
        # Но runtime_override может переключить на другой runtime → нужна проверка.
        if runtime_override and name != getattr(config, "runtime_name", name):
            cap_error = self.validate_capabilities(
                config=effective_config,
                runtime_override=runtime_override,
            )
            if cap_error is not None:
                return _ErrorRuntime(cap_error)

        if name == "claude_sdk":
            return self._create_claude_code(effective_config, **kwargs)
        elif name == "deepagents":
            return self._create_deepagents(effective_config, **kwargs)
        elif name == "thin":
            return self._create_thin(effective_config, **kwargs)
        else:
            raise ValueError(
                f"Неизвестный runtime: '{name}'. "
                f"Допустимые: {', '.join(sorted(VALID_RUNTIME_NAMES))}"
            )

    def _create_claude_code(
        self,
        config: RuntimeConfig,
        **kwargs: Any,
    ) -> AgentRuntime:
        """Создать ClaudeCodeRuntime."""
        try:
            from cognitia.runtime.claude_code import ClaudeCodeRuntime

            return ClaudeCodeRuntime(config=config, **kwargs)
        except ImportError:
            return _ErrorRuntime(
                RuntimeErrorData(
                    kind="dependency_missing",
                    message="claude-agent-sdk не установлен. Установите: pip install cognitia",
                    recoverable=False,
                )
            )

    def _create_deepagents(
        self,
        config: RuntimeConfig,
        **kwargs: Any,
    ) -> AgentRuntime:
        """Создать DeepAgentsRuntime."""
        try:
            from cognitia.runtime.deepagents import DeepAgentsRuntime

            return DeepAgentsRuntime(config=config, **kwargs)
        except ImportError:
            return _ErrorRuntime(
                RuntimeErrorData(
                    kind="dependency_missing",
                    message=(
                        "langchain-core не установлен. Установите: pip install cognitia[deepagents]"
                    ),
                    recoverable=False,
                )
            )

    def _create_thin(
        self,
        config: RuntimeConfig,
        **kwargs: Any,
    ) -> AgentRuntime:
        """Создать ThinRuntime."""
        try:
            from cognitia.runtime.thin import ThinRuntime

            local_tools = dict(kwargs.pop("local_tools", {}) or {})
            tool_executors = kwargs.pop("tool_executors", None) or {}
            if tool_executors:
                local_tools.update(tool_executors)
                kwargs["local_tools"] = local_tools

            return ThinRuntime(config=config, **kwargs)
        except ImportError:
            return _ErrorRuntime(
                RuntimeErrorData(
                    kind="dependency_missing",
                    message=("anthropic не установлен. Установите: pip install cognitia[thin]"),
                    recoverable=False,
                )
            )


class _ErrorRuntime:
    """Заглушка runtime — возвращает ошибку при вызове run().

    Используется когда optional dependency не установлен.
    """

    def __init__(self, error: RuntimeErrorData) -> None:
        self._error = error

    async def run(
        self,
        **kwargs: Any,
    ) -> AsyncIterator[RuntimeEvent]:
        """Yield ошибку и завершиться."""
        yield RuntimeEvent.error(self._error)

    async def cleanup(self) -> None:
        """Нечего очищать."""
