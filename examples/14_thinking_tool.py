"""Thinking tool: structured Chain-of-Thought + ReAct reasoning.

Demonstrates: create_thinking_tool() -- tool spec and executor.
No API keys required.
"""

import asyncio

from swarmline.tools.thinking import create_thinking_tool


async def main() -> None:
    # 1. Create the thinking tool
    tool_spec, executor = create_thinking_tool()

    print("=== Thinking Tool Spec ===")
    print(f"Name: {tool_spec.name}")
    print(f"Description: {tool_spec.description}")
    print(f"Parameters: {tool_spec.parameters}")

    # 2. Simulate agent using the thinking tool for reasoning
    print("\n=== Simulated Reasoning Steps ===")

    # Step 1: Analyze the problem
    result1 = await executor({
        "thought": "The user asked to compare Python and Rust for a web backend. "
                   "I need to consider performance, ecosystem, learning curve, and use cases.",
        "next_steps": [
            "Research Python web frameworks (FastAPI, Django)",
            "Research Rust web frameworks (Actix, Axum)",
            "Compare performance benchmarks",
        ],
    })
    print(f"Step 1: {result1}")

    # Step 2: Deeper analysis
    result2 = await executor({
        "thought": "Python has FastAPI (async, fast dev) and Django (batteries-included). "
                   "Rust has Actix-web (fastest benchmarks) and Axum (ergonomic). "
                   "For most web backends, Python's ecosystem advantage outweighs Rust's raw speed.",
        "next_steps": [
            "Formulate recommendation based on user's needs",
            "Provide concrete examples for each option",
        ],
    })
    print(f"Step 2: {result2}")

    # 3. The thinking tool is added to agent tools automatically
    print("\n=== Usage with Agent ===")
    print("# The thinking tool gives the agent a 'scratchpad' for reasoning:")
    print("# agent = Agent(AgentConfig(")
    print("#     system_prompt='You are a tech advisor.',")
    print("#     runtime='thin',")
    print("# ))")
    print("# The runtime can inject thinking_tool into active_tools")


if __name__ == "__main__":
    asyncio.run(main())
