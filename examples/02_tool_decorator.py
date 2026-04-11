"""@tool decorator with auto-inferred JSON Schema from type hints.

Demonstrates: @tool decorator, ToolDefinition, to_tool_spec().
No API keys required.
"""

import asyncio

from swarmline.agent.tool import tool


@tool("get_weather", description="Get current weather for a city.")
async def get_weather(city: str, units: str = "celsius") -> str:
    """Get current weather for a city.

    Args:
        city: City name to look up.
        units: Temperature units (celsius or fahrenheit).
    """
    return f"Weather in {city}: 22 {units}, sunny"


@tool("add_numbers")
def add_numbers(a: int, b: int) -> str:
    """Add two numbers together.

    Args:
        a: First number.
        b: Second number.
    """
    return str(a + b)


async def main() -> None:
    # 1. Access the auto-generated ToolDefinition
    defn = get_weather.__tool_definition__
    print(f"Tool: {defn.name}")
    print(f"Description: {defn.description}")
    print(f"Parameters: {defn.parameters}")

    # 2. Convert to ToolSpec (runtime-ready format)
    spec = defn.to_tool_spec()
    print(f"ToolSpec: name={spec.name}, is_local={spec.is_local}")

    # 3. Call the tool handler directly
    result = await defn.handler(city="Berlin")
    print(f"Result: {result}")

    # 4. Sync functions are auto-wrapped as async
    calc_defn = add_numbers.__tool_definition__
    calc_result = await calc_defn.handler(a=2, b=3)
    print(f"Sum: {calc_result}")

    # 5. Use tools with Agent (requires API key)
    # agent = Agent(AgentConfig(
    #     system_prompt="You help with weather.",
    #     runtime="thin",
    #     tools=(get_weather, add_numbers),
    # ))
    # result = await agent.query("What's the weather in Paris?")


if __name__ == "__main__":
    asyncio.run(main())
