"""Base module — re-exports AgentRuntime from protocols layer.

AgentRuntime Protocol is now defined in swarmline.protocols.runtime (Domain layer).
This module re-exports it for backward compatibility.
"""

from swarmline.protocols.runtime import AgentRuntime  # noqa: F401
