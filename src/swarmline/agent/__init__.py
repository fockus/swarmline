"""swarmline.agent - high-level facade for integrating swarmline into applications."""

from swarmline.agent.agent import Agent
from swarmline.agent.config import AgentConfig
from swarmline.agent.conversation import Conversation
from swarmline.agent.middleware import (
    BudgetExceededError,
    CostTracker,
    Middleware,
    SecurityGuard,
    ToolOutputCompressor,
    build_middleware_stack,
)
from swarmline.agent.result import Result
from swarmline.agent.structured import StructuredOutputError
from swarmline.agent.tool import ToolDefinition, tool
from swarmline.agent.tool_protocol import ToolFunction

__all__ = [
    "Agent",
    "AgentConfig",
    "BudgetExceededError",
    "Conversation",
    "CostTracker",
    "Middleware",
    "Result",
    "StructuredOutputError",
    "SecurityGuard",
    "ToolDefinition",
    "ToolFunction",
    "ToolOutputCompressor",
    "build_middleware_stack",
    "tool",
]
