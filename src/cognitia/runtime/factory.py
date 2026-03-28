"""Factory module."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from cognitia.runtime.capabilities import (
    CapabilityRequirements,
    RuntimeCapabilities,
)
from cognitia.runtime.types import (
    VALID_RUNTIME_NAMES,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
)

if TYPE_CHECKING:
    from cognitia.runtime.registry import RuntimeRegistry


class RuntimeFactory:
    """Runtime Factory implementation."""

    def __init__(self, registry: RuntimeRegistry | None = None) -> None:
        self._registry = registry

    @property
    def _effective_registry(self) -> RuntimeRegistry | None:
        """Lazy resolve registry: explicit > default singleton."""
        if self._registry is not None:
            return self._registry
        try:
            from cognitia.runtime.registry import get_default_registry

            return get_default_registry()
        except Exception:
            return None

    def _is_valid_name(self, name: str) -> bool:
        """Check if name is valid (static set + registry)."""
        if name in VALID_RUNTIME_NAMES:
            return True
        registry = self._effective_registry
        if registry is not None and registry.is_registered(name):
            return True
        return False

    def resolve_runtime_name(
        self,
        config: RuntimeConfig | None = None,
        runtime_override: str | None = None,
    ) -> str:
        """Resolve runtime name."""

        if runtime_override and self._is_valid_name(runtime_override):
            return runtime_override


        if config and self._is_valid_name(config.runtime_name):
            return config.runtime_name


        env_runtime = os.environ.get("COGNITIA_RUNTIME", "").strip().lower()
        if self._is_valid_name(env_runtime):
            return env_runtime

        # 4. Default
        return "claude_sdk"

    def get_capabilities(
        self,
        config: RuntimeConfig | None = None,
        runtime_override: str | None = None,
    ) -> RuntimeCapabilities:
        """Get capabilities."""
        from cognitia.runtime.registry import resolve_runtime_capabilities

        name = self.resolve_runtime_name(config, runtime_override)
        return resolve_runtime_capabilities(name, registry=self._effective_registry)

    def validate_capabilities(
        self,
        config: RuntimeConfig | None = None,
        runtime_override: str | None = None,
        required_capabilities: CapabilityRequirements | None = None,
    ) -> RuntimeErrorData | None:
        """Validate capabilities."""
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
                f"Runtime '{caps.runtime_name}' does not support required capabilities: "
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
    ) -> Any:
        """Create."""
        name = self.resolve_runtime_name(config, runtime_override)
        effective_config = config or RuntimeConfig(runtime_name=name)



        if runtime_override and name != getattr(config, "runtime_name", name):
            cap_error = self.validate_capabilities(
                config=effective_config,
                runtime_override=runtime_override,
            )
            if cap_error is not None:
                return _ErrorRuntime(cap_error)

        # Try registry first (supports builtins + custom runtimes)
        registry = self._effective_registry
        if registry is not None:
            factory_fn = registry.get(name)
            if factory_fn is not None:
                try:
                    return factory_fn(effective_config, **kwargs)
                except ImportError:
                    return _ErrorRuntime(
                        RuntimeErrorData(
                            kind="dependency_missing",
                            message=f"Dependencies for runtime '{name}' not installed.",
                            recoverable=False,
                        )
                    )

        # Fallback: legacy if/elif for backward compat (if registry unavailable)
        if name == "claude_sdk":
            return self._create_claude_code(effective_config, **kwargs)
        elif name == "deepagents":
            return self._create_deepagents(effective_config, **kwargs)
        elif name == "thin":
            return self._create_thin(effective_config, **kwargs)
        elif name == "cli":
            from cognitia.runtime.registry import _create_cli

            return _create_cli(effective_config, **kwargs)
        elif name == "openai_agents":
            from cognitia.runtime.registry import _create_openai_agents

            return _create_openai_agents(effective_config, **kwargs)
        else:
            raise ValueError(
                f"Unknown runtime: '{name}'. "
                f"Allowed: {', '.join(sorted(VALID_RUNTIME_NAMES))}"
            )

    def _create_claude_code(
        self,
        config: RuntimeConfig,
        **kwargs: Any,
    ) -> Any:
        """Create ClaudeCodeRuntime."""
        try:
            from cognitia.runtime.claude_code import ClaudeCodeRuntime

            return ClaudeCodeRuntime(config=config, **kwargs)
        except ImportError:
            return _ErrorRuntime(
                RuntimeErrorData(
                    kind="dependency_missing",
                    message="claude-agent-sdk is not installed. Install: pip install cognitia",
                    recoverable=False,
                )
            )

    def _create_deepagents(
        self,
        config: RuntimeConfig,
        **kwargs: Any,
    ) -> Any:
        """Create DeepAgentsRuntime."""
        try:
            from cognitia.runtime.deepagents import DeepAgentsRuntime

            return DeepAgentsRuntime(config=config, **kwargs)
        except ImportError:
            return _ErrorRuntime(
                RuntimeErrorData(
                    kind="dependency_missing",
                    message=(
                        "langchain-core is not installed. Install: pip install cognitia[deepagents]"
                    ),
                    recoverable=False,
                )
            )

    def _create_thin(
        self,
        config: RuntimeConfig,
        **kwargs: Any,
    ) -> Any:
        """Create ThinRuntime."""
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
                    message=("anthropic is not installed. Install: pip install cognitia[thin]"),
                    recoverable=False,
                )
            )


class _ErrorRuntime:
    """Error Runtime implementation."""

    def __init__(self, error: RuntimeErrorData) -> None:
        self._error = error

    async def run(
        self,
        **kwargs: Any,
    ) -> AsyncIterator[RuntimeEvent]:
        """Run."""
        yield RuntimeEvent.error(self._error)

    async def cleanup(self) -> None:
        """Cleanup."""
