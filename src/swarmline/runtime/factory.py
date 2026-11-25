"""Factory module."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from swarmline.runtime.capabilities import (
    VALID_FEATURE_MODES,
    CapabilityRequirements,
    RuntimeCapabilities,
    get_runtime_capabilities as get_runtime_capabilities_static,
)
from swarmline.runtime.types import (
    VALID_RUNTIME_NAMES,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
)

if TYPE_CHECKING:
    from swarmline.agent.config import AgentConfig
    from swarmline.runtime.registry import RuntimeRegistry


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
            from swarmline.runtime.registry import get_default_registry

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

        env_runtime = os.environ.get("SWARMLINE_RUNTIME", "").strip().lower()
        if self._is_valid_name(env_runtime):
            return env_runtime

        # 4. Default — unified with the Agent facade default (plan E2)
        return "thin"

    def get_capabilities(
        self,
        config: RuntimeConfig | None = None,
        runtime_override: str | None = None,
    ) -> RuntimeCapabilities:
        """Get capabilities."""
        from swarmline.runtime.registry import resolve_runtime_capabilities

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
        caps = caps.resolve(config)
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

    def validate_agent_config(self, config: AgentConfig) -> None:
        """Validate AgentConfig at the runtime/bootstrap boundary."""
        from swarmline.runtime.registry import get_valid_runtime_names

        valid_names = get_valid_runtime_names()
        if config.runtime not in valid_names:
            raise ValueError(
                f"Unknown runtime: '{config.runtime}'. "
                f"Allowed: {', '.join(sorted(valid_names))}"
            )
        if config.feature_mode not in VALID_FEATURE_MODES:
            raise ValueError(
                f"Unknown feature_mode: '{config.feature_mode}'. "
                f"Allowed: {', '.join(sorted(VALID_FEATURE_MODES))}"
            )

        self._validate_config_against_capabilities(config)

        if config.require_capabilities is None:
            return

        caps = self.get_capabilities(runtime_override=config.runtime).resolve(config)
        missing = caps.missing(config.require_capabilities)
        if missing:
            raise ValueError(
                f"Runtime '{config.runtime}' does not support required capabilities: "
                f"{', '.join(missing)}"
            )

    def _validate_config_against_capabilities(self, config: AgentConfig) -> None:
        """No-silent-drop: every config option maps to a runtime capability.

        An option the selected runtime cannot deliver raises ValueError
        (or warns when ``strict_capabilities=False``). Applies only to the
        built-in runtimes — custom registry runtimes may not have adopted
        the fine-grained capability model.
        """
        if config.runtime not in VALID_RUNTIME_NAMES:
            return

        caps = self.get_capabilities(runtime_override=config.runtime).resolve(config)

        thinking_enabled = (
            isinstance(config.thinking, dict)
            and dict(config.thinking).get("type") != "disabled"
        )

        checks: list[tuple[str, str, bool]] = [
            ("mcp_servers", "mcp", bool(config.mcp_servers)),
            (
                "output_format/output_type",
                "structured_output",
                config.output_format is not None or config.output_type is not None,
            ),
            ("thinking", "thinking_stream", thinking_enabled),
            ("max_budget_usd", "cost_tracking", config.max_budget_usd is not None),
            (
                "resume_session_id",
                "resume",
                config.resume_session_id is not None,
            ),
            ("can_use_tool", "permissions", config.can_use_tool is not None),
            (
                "tool_policy",
                "permissions",
                getattr(config, "tool_policy", None) is not None,
            ),
            (
                "base_url/api_key",
                "provider_override",
                bool(getattr(config, "base_url", None))
                or bool(getattr(config, "api_key", None)),
            ),
            (
                "native_agents",
                "subagents:native",
                bool(config.native_agents),
            ),
            (
                "subagent_config",
                "subagents",
                config.subagent_config is not None,
            ),
            (
                "coding_profile",
                "builtin_tools",
                config.coding_profile is not None,
            ),
            (
                "project_instructions",
                "project_instructions",
                bool(config.project_instructions),
            ),
        ]

        from swarmline.runtime.capabilities import parse_capability_flag

        violations: list[str] = []
        for option, flag, present in checks:
            if not present:
                continue
            dimension, min_level = parse_capability_flag(flag)
            actual = caps.level(dimension)
            order = {"none": 0, "emulated": 1, "native": 2}
            if order[actual] < order[min_level]:
                capable = sorted(
                    name
                    for name in VALID_RUNTIME_NAMES
                    if name != "headless"
                    and order[get_runtime_capabilities_static(name).level(dimension)]
                    >= order[min_level]
                )
                violations.append(
                    f"'{option}' requires capability '{flag}' which runtime "
                    f"'{config.runtime}' does not provide"
                    + (f" (supported by: {', '.join(capable)})" if capable else "")
                )

        if not violations:
            return

        message = (
            f"AgentConfig options unsupported by runtime '{config.runtime}':\n  - "
            + "\n  - ".join(violations)
        )
        if getattr(config, "strict_capabilities", True):
            raise ValueError(
                message
                + "\nSet strict_capabilities=False to degrade with a warning instead."
            )
        import warnings

        warnings.warn(message + " — degrading.", UserWarning, stacklevel=3)

    def resolve_agent_model(self, config: AgentConfig | str) -> str:
        """Resolve AgentConfig.model or a raw alias to a concrete model name."""
        from swarmline.runtime.types import resolve_model_name

        model = config.model if hasattr(config, "model") else config
        return resolve_model_name(model)  # ty: ignore[invalid-argument-type]  # model narrowed by hasattr check above; ty doesn't propagate

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
            from swarmline.runtime.registry import _create_cli

            return _create_cli(effective_config, **kwargs)
        elif name == "openai_agents":
            from swarmline.runtime.registry import _create_openai_agents

            return _create_openai_agents(effective_config, **kwargs)
        elif name == "pi_sdk":
            from swarmline.runtime.registry import _create_pi_sdk

            return _create_pi_sdk(effective_config, **kwargs)
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
            from swarmline.runtime.claude_code import ClaudeCodeRuntime

            return ClaudeCodeRuntime(config=config, **kwargs)
        except ImportError:
            return _ErrorRuntime(
                RuntimeErrorData(
                    kind="dependency_missing",
                    message="claude-agent-sdk is not installed. Install: pip install swarmline",
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
            from swarmline.runtime.deepagents import DeepAgentsRuntime

            return DeepAgentsRuntime(config=config, **kwargs)
        except ImportError:
            return _ErrorRuntime(
                RuntimeErrorData(
                    kind="dependency_missing",
                    message=(
                        "langchain-core is not installed. Install: pip install swarmline[deepagents]"
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
            from swarmline.runtime.thin import ThinRuntime

            local_tools = dict(kwargs.pop("local_tools", {}) or {})
            tool_executors = kwargs.pop("tool_executors", None) or {}
            if tool_executors:
                local_tools.update(tool_executors)
            if local_tools:
                kwargs["local_tools"] = local_tools

            return ThinRuntime(config=config, **kwargs)
        except ImportError:
            return _ErrorRuntime(
                RuntimeErrorData(
                    kind="dependency_missing",
                    message=(
                        "anthropic is not installed. Install: pip install swarmline[thin]"
                    ),
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
