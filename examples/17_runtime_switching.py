"""Runtime switching: same code, different execution engines.

Demonstrates: RuntimeFactory, RuntimeRegistry, RuntimeCapabilities,
CapabilityRequirements, get_default_registry.
No API keys required.
"""

import asyncio

from swarmline.runtime.capabilities import (
    CapabilityRequirements,
    get_runtime_capabilities,
)
from swarmline.runtime.factory import RuntimeFactory
from swarmline.runtime.registry import get_default_registry


async def main() -> None:
    # 1. List all registered runtimes
    print("=== Available Runtimes ===")
    registry = get_default_registry()
    for name in registry.list_available():
        caps = registry.get_capabilities(name)
        tier = caps.tier if caps else "unknown"
        flags = ", ".join(caps.enabled_flags()) if caps else "none"
        print(f"  {name}: tier={tier}, flags=[{flags}]")

    # 2. Compare capabilities
    print("\n=== Capability Comparison ===")
    for runtime_name in ["claude_sdk", "thin", "deepagents", "cli"]:
        caps = get_runtime_capabilities(runtime_name)
        print(f"\n  {runtime_name}:")
        print(f"    Tier: {caps.tier}")
        print(f"    MCP: {caps.supports_mcp}")
        print(f"    Resume: {caps.supports_resume}")
        print(f"    Interrupt: {caps.supports_interrupt}")
        print(f"    Provider override: {caps.supports_provider_override}")

    # 3. Capability requirements and validation
    print("\n=== Capability Validation ===")
    reqs = CapabilityRequirements(flags=("mcp", "provider_override"))

    for runtime_name in ["thin", "cli", "claude_sdk"]:
        caps = get_runtime_capabilities(runtime_name)
        supported = caps.supports(reqs)
        missing = caps.missing(reqs)
        status = "OK" if supported else f"MISSING: {missing}"
        print(f"  {runtime_name}: {status}")

    # 4. RuntimeFactory -- create runtime by config
    print("\n=== RuntimeFactory ===")
    factory = RuntimeFactory(registry=registry)

    # Resolve runtime name (priority: override > config > env)
    resolved = factory.resolve_runtime_name(runtime_override="thin")
    print(f"Resolved: {resolved}")

    # Pre-flight validation
    validation_error = factory.validate_capabilities(
        config=None,
        runtime_override="cli",
        required_capabilities=CapabilityRequirements(flags=("mcp",)),
    )
    if validation_error:
        print(f"Validation failed: {validation_error.message}")

    # 5. Same Agent code, different runtimes (requires API key)
    # from swarmline import Agent, AgentConfig
    # for runtime in ["thin", "claude_sdk", "deepagents"]:
    #     agent = Agent(AgentConfig(system_prompt="Hi", runtime=runtime))
    #     result = await agent.query("Hello")
    #     print(f"{runtime}: {result.text}")


if __name__ == "__main__":
    asyncio.run(main())
