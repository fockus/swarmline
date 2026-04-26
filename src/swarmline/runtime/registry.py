"""RuntimeRegistry - extensible adapter registry for runtime factories.

Built-in runtimes (`claude_sdk`, `deepagents`, `thin`, `cli`, `openai_agents`,
`pi_sdk`, `headless`)
are registered automatically. Third-party runtimes can be registered via
register() or entry points (group="swarmline.runtimes").
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any

from swarmline.runtime.capabilities import (
    RuntimeCapabilities,
    get_runtime_capabilities,
)
from swarmline.runtime.types import RuntimeConfig

logger = logging.getLogger(__name__)


class RuntimeRegistry:
    """Thread-safe extensible registry for runtime factories.

    Each entry maps a runtime name to:
    - factory_fn: Callable[[RuntimeConfig, ...], AgentRuntime]
    - capabilities: RuntimeCapabilities | None
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._factories: dict[str, Callable[..., Any]] = {}
        self._capabilities: dict[str, RuntimeCapabilities] = {}

    def register(
        self,
        name: str,
        factory_fn: Callable[..., Any],
        capabilities: RuntimeCapabilities | None = None,
    ) -> None:
        """Register a runtime factory by name. Overwrites if exists."""
        with self._lock:
            self._factories[name] = factory_fn
            if capabilities is not None:
                self._capabilities[name] = capabilities
            elif name in self._capabilities:
                # Keep existing capabilities if re-registering without new ones
                pass

    def unregister(self, name: str) -> bool:
        """Remove a runtime. Returns True if existed."""
        with self._lock:
            existed = name in self._factories
            self._factories.pop(name, None)
            self._capabilities.pop(name, None)
            return existed

    def get(self, name: str) -> Callable[..., Any] | None:
        """Get factory function by name."""
        with self._lock:
            return self._factories.get(name)

    def get_capabilities(self, name: str) -> RuntimeCapabilities | None:
        """Get capabilities for registered runtime."""
        with self._lock:
            return self._capabilities.get(name)

    def list_available(self) -> list[str]:
        """List all registered runtime names."""
        with self._lock:
            return list(self._factories.keys())

    def is_registered(self, name: str) -> bool:
        """Check if a runtime is registered."""
        with self._lock:
            return name in self._factories


# ---------------------------------------------------------------------------
# Built-in runtime factories (lazy imports)
# ---------------------------------------------------------------------------


def _create_claude_sdk(config: RuntimeConfig, **kwargs: Any) -> Any:
    """Lazy factory for ClaudeCodeRuntime."""
    from swarmline.runtime.claude_code import ClaudeCodeRuntime

    return ClaudeCodeRuntime(config=config, **kwargs)


def _create_deepagents(config: RuntimeConfig, **kwargs: Any) -> Any:
    """Lazy factory for DeepAgentsRuntime."""
    from swarmline.runtime.deepagents import DeepAgentsRuntime

    return DeepAgentsRuntime(config=config, **kwargs)


def _create_thin(config: RuntimeConfig, **kwargs: Any) -> Any:
    """Lazy factory for ThinRuntime."""
    local_tools = dict(kwargs.pop("local_tools", {}) or {})
    tool_executors = kwargs.pop("tool_executors", None) or {}
    if tool_executors:
        local_tools.update(tool_executors)
        kwargs["local_tools"] = local_tools

    from swarmline.runtime.thin import ThinRuntime

    return ThinRuntime(config=config, **kwargs)


def _create_cli(config: RuntimeConfig, **kwargs: Any) -> Any:
    """Lazy factory for CliAgentRuntime."""
    from swarmline.runtime.cli.runtime import CliAgentRuntime

    kwargs.pop("tool_executors", None)
    kwargs.pop("local_tools", None)
    kwargs.pop("mcp_servers", None)
    return CliAgentRuntime(config=config, **kwargs)


def _create_headless(config: RuntimeConfig, **kwargs: Any) -> Any:
    """Lazy factory for HeadlessRuntime."""
    from swarmline.runtime.headless import HeadlessRuntime

    return HeadlessRuntime(config, **kwargs)


def _create_openai_agents(config: RuntimeConfig, **kwargs: Any) -> Any:
    """Lazy factory for OpenAIAgentsRuntime."""
    from swarmline.runtime.openai_agents.runtime import OpenAIAgentsRuntime
    from swarmline.runtime.openai_agents.tool_bridge import build_tool_executor

    tool_handlers = dict(kwargs.pop("local_tools", {}) or {})
    tool_handlers.update(kwargs.pop("tool_executors", {}) or {})
    if tool_handlers and "tool_executor" not in kwargs:
        kwargs["tool_executor"] = build_tool_executor(tool_handlers)

    mcp_servers = kwargs.pop("mcp_servers", None)
    if mcp_servers:
        raise ValueError(
            "runtime='openai_agents' does not support AgentConfig.mcp_servers yet. "
            "Use OpenAIAgentsConfig.codex_enabled for Codex MCP, or choose runtime='thin' "
            "or runtime='deepagents' for Swarmline MCP bridge support."
        )
    return OpenAIAgentsRuntime(config=config, **kwargs)


def _create_pi_sdk(config: RuntimeConfig, **kwargs: Any) -> Any:
    """Lazy factory for PiSdkRuntime."""
    from swarmline.runtime.pi_sdk.runtime import PiSdkRuntime

    mcp_servers = kwargs.pop("mcp_servers", None)
    if mcp_servers:
        raise ValueError(
            "runtime='pi_sdk' does not support AgentConfig.mcp_servers. "
            "Use PI extensions/skills inside PI, or choose runtime='thin' or runtime='deepagents' "
            "for Swarmline MCP bridge support."
        )
    return PiSdkRuntime(config=config, **kwargs)


def _register_builtins(registry: RuntimeRegistry) -> None:
    """Register built-in runtimes."""
    registry.register(
        "claude_sdk",
        _create_claude_sdk,
        capabilities=get_runtime_capabilities("claude_sdk"),
    )
    registry.register(
        "deepagents",
        _create_deepagents,
        capabilities=get_runtime_capabilities("deepagents"),
    )
    registry.register(
        "thin",
        _create_thin,
        capabilities=get_runtime_capabilities("thin"),
    )
    registry.register(
        "cli",
        _create_cli,
        capabilities=get_runtime_capabilities("cli"),
    )
    registry.register(
        "openai_agents",
        _create_openai_agents,
        capabilities=get_runtime_capabilities("openai_agents"),
    )
    registry.register(
        "pi_sdk",
        _create_pi_sdk,
        capabilities=get_runtime_capabilities("pi_sdk"),
    )
    registry.register(
        "headless",
        _create_headless,
        capabilities=get_runtime_capabilities("headless"),
    )


# ---------------------------------------------------------------------------
# Entry point discovery
# ---------------------------------------------------------------------------


def _discover_entry_points(registry: RuntimeRegistry) -> None:
    """Discover and register runtimes from entry points (group='swarmline.runtimes').

    Each entry point should return a tuple of (factory_fn, capabilities).
    Bad plugins are silently skipped with a warning.
    """
    try:
        eps = entry_points(group="swarmline.runtimes")
    except Exception:
        return

    for ep in eps:
        try:
            result = ep.load()
            if not isinstance(result, tuple) or len(result) != 2:
                logger.warning(
                    "Entry point '%s' returned invalid format (expected tuple of 2), skipping.",
                    ep.name,
                )
                continue
            factory_fn, capabilities = result
            registry.register(ep.name, factory_fn, capabilities=capabilities)
        except Exception:
            logger.warning(
                "Failed to load entry point '%s', skipping.",
                ep.name,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Default singleton registry
# ---------------------------------------------------------------------------

_default_registry: RuntimeRegistry | None = None
_default_lock = threading.Lock()


def get_default_registry() -> RuntimeRegistry:
    """Get the default singleton registry with builtins and entry points."""
    global _default_registry
    if _default_registry is not None:
        return _default_registry
    with _default_lock:
        if _default_registry is not None:
            return _default_registry
        registry = RuntimeRegistry()
        _register_builtins(registry)
        _discover_entry_points(registry)
        _default_registry = registry
        return registry


def reset_default_registry() -> None:
    """Reset the default registry (for testing)."""
    global _default_registry
    with _default_lock:
        _default_registry = None


# ---------------------------------------------------------------------------
# Dynamic valid runtime names
# ---------------------------------------------------------------------------

_BUILTIN_NAMES = frozenset(
    {"claude_sdk", "deepagents", "thin", "cli", "openai_agents", "pi_sdk", "headless"}
)


def get_valid_runtime_names() -> frozenset[str]:
    """Get valid runtime names from registry + hardcoded builtins.

    Returns frozenset combining builtins and any registered custom runtimes.
    """
    try:
        registry = get_default_registry()
        return frozenset(registry.list_available()) | _BUILTIN_NAMES
    except Exception:
        return _BUILTIN_NAMES


def resolve_runtime_capabilities(
    runtime_name: str,
    registry: RuntimeRegistry | None = None,
) -> RuntimeCapabilities:
    """Resolve capabilities for built-in or registry-registered runtime.

    Built-ins fall back to the static capability table. Custom runtimes must
    register capabilities explicitly to participate in capability negotiation.
    """
    effective_registry = registry
    if effective_registry is None:
        try:
            effective_registry = get_default_registry()
        except Exception:
            effective_registry = None

    if effective_registry is not None:
        caps = effective_registry.get_capabilities(runtime_name)
        if caps is not None:
            return caps
        if (
            effective_registry.is_registered(runtime_name)
            and runtime_name not in _BUILTIN_NAMES
        ):
            raise ValueError(
                f"Capabilities not registered for runtime: '{runtime_name}'"
            )

    return get_runtime_capabilities(runtime_name)
