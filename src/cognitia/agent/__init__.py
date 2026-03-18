"""cognitia.agent - high-level facade for integrating cognitia into applications."""

from cognitia.agent.agent import Agent
from cognitia.agent.config import AgentConfig
from cognitia.agent.conversation import Conversation
from cognitia.agent.middleware import (
    BudgetExceededError,
    CostTracker,
    Middleware,
    SecurityGuard,
    ToolOutputCompressor,
    build_middleware_stack,
)
from cognitia.agent.result import Result
from cognitia.agent.tool import ToolDefinition, tool

__all__ = [
    "Agent",
    "AgentConfig",
    "BudgetExceededError",
    "Conversation",
    "CostTracker",
    "Middleware",
    "Result",
    "SecurityGuard",
    "ToolOutputCompressor",
    "build_middleware_stack",
    "ToolDefinition",
    "tool",
]
