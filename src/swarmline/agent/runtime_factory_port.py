"""Port for runtime factory interactions used by the Agent application layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from swarmline.agent.config import AgentConfig
    from swarmline.runtime.capabilities import (
        CapabilityRequirements,
        RuntimeCapabilities,
    )
    from swarmline.runtime.types import RuntimeConfig, RuntimeErrorData


@runtime_checkable
class RuntimeFactoryPort(Protocol):
    """Application-facing runtime factory seam.

    The Agent layer depends on this protocol instead of the concrete
    `swarmline.runtime.factory.RuntimeFactory` implementation.
    """

    def validate_agent_config(self, config: AgentConfig) -> None:
        """Validate AgentConfig at the runtime/composition boundary."""

    def resolve_agent_model(self, config: AgentConfig | str) -> str:
        """Resolve model aliases to concrete model names."""

    def get_capabilities(
        self,
        config: RuntimeConfig | None = None,
        runtime_override: str | None = None,
    ) -> RuntimeCapabilities:
        """Return capability metadata for the selected runtime."""

    def validate_capabilities(
        self,
        config: RuntimeConfig | None = None,
        runtime_override: str | None = None,
        required_capabilities: CapabilityRequirements | None = None,
    ) -> RuntimeErrorData | None:
        """Validate runtime capabilities against the requested requirements."""

    def create(
        self,
        config: RuntimeConfig | None = None,
        runtime_override: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Create the selected runtime implementation."""


def build_runtime_factory() -> RuntimeFactoryPort:
    """Build the default runtime factory adapter.

    Concrete factory construction is intentionally isolated here so the rest of
    the Agent application layer only depends on `RuntimeFactoryPort`.
    """

    from swarmline.runtime.factory import RuntimeFactory

    return RuntimeFactory()
