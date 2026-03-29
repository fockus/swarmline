"""Base module — re-exports AgentRuntime from protocols layer.

AgentRuntime Protocol is now defined in cognitia.protocols.runtime (Domain layer).
This module re-exports it for backward compatibility.
"""

from cognitia.protocols.runtime import AgentRuntime  # noqa: F401
