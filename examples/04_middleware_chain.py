"""Middleware pipeline: cost tracking, security, and tool output compression.

Demonstrates: CostTracker, SecurityGuard, ToolOutputCompressor,
build_middleware_stack, custom Middleware.
No API keys required.
"""

import asyncio

from swarmline.agent.config import AgentConfig
from swarmline.agent.middleware import (
    CostTracker,
    Middleware,
    SecurityGuard,
    ToolOutputCompressor,
    build_middleware_stack,
)
from swarmline.agent.result import Result


# --- Custom middleware ---
class LoggingMiddleware(Middleware):
    """Logs prompts and results passing through the pipeline."""

    async def before_query(self, prompt: str, config: AgentConfig) -> str:
        print(f"  [LOG] Prompt: {prompt[:50]}...")
        return prompt

    async def after_result(self, result: Result) -> Result:
        print(f"  [LOG] Result: {result.text[:50]}...")
        return result


async def main() -> None:
    # 1. CostTracker -- accumulate costs, enforce budget
    tracker = CostTracker(budget_usd=5.0)
    print(f"Spent so far: ${tracker.total_cost_usd}")

    # 2. SecurityGuard -- blocks tool calls matching patterns
    guard = SecurityGuard(block_patterns=["password", "secret", "api_key"])
    hooks = guard.get_hooks()
    print(f"SecurityGuard hooks: {hooks.list_events() if hooks else 'none'}")

    # 3. ToolOutputCompressor -- truncate large tool outputs
    compressor = ToolOutputCompressor(max_result_chars=100)
    long_text = "x" * 500
    compressed = compressor.compress(long_text)
    print(f"Compressed {len(long_text)} chars -> {len(compressed)} chars")

    # 4. build_middleware_stack -- convenience factory
    stack = build_middleware_stack(
        cost_tracker=True,
        budget_usd=10.0,
        tool_compressor=True,
        max_result_chars=5000,
        security_guard=True,
        blocked_patterns=["rm -rf", "DROP TABLE"],
    )
    print(f"Stack size: {len(stack)} middleware(s)")
    for mw in stack:
        print(f"  - {type(mw).__name__}")

    # 5. Custom middleware in action
    logger = LoggingMiddleware()
    config = AgentConfig(system_prompt="test")
    _ = await logger.before_query("Hello, how are you today?", config)
    mock_result = Result(text="I'm doing great!", session_id="s1")
    _ = await logger.after_result(mock_result)

    # 6. Compose into Agent (requires API key)
    # agent = Agent(AgentConfig(
    #     system_prompt="Helpful assistant",
    #     runtime="thin",
    #     middleware=(tracker, guard, compressor, logger),
    # ))


if __name__ == "__main__":
    asyncio.run(main())
