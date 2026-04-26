"""Integration: @tool decorator — ToolSpec compatibility and callable execution."""

from __future__ import annotations

import enum

import pytest
from pydantic import BaseModel

from swarmline.agent.tool import ToolDefinition, tool
from swarmline.runtime.types import ToolSpec


class Priority(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskInput(BaseModel):
    title: str
    priority: Priority


class TestToolDecoratorProducesValidToolspec:
    def test_tool_decorator_produces_valid_toolspec(self) -> None:
        """@tool fn -> ToolSpec compatible with ThinRuntime."""

        @tool(name="create_task")
        def create_task(
            title: str, priority: Priority, tags: list[str], metadata: dict
        ) -> str:
            """Create a new task.

            Args:
                title: The task title.
                priority: Task priority level.
                tags: List of tags.
                metadata: Additional metadata.
            """
            return f"Created: {title}"

        td: ToolDefinition = create_task.__tool_definition__
        spec = td.to_tool_spec()

        # ToolSpec is valid
        assert isinstance(spec, ToolSpec)
        assert spec.name == "create_task"
        assert spec.description == "Create a new task."
        assert spec.is_local is True

        # Parameters schema is valid JSON Schema
        params = spec.parameters
        assert params["type"] == "object"
        assert "title" in params["properties"]
        assert "priority" in params["properties"]
        assert "tags" in params["properties"]
        assert "metadata" in params["properties"]

        # Types are correct
        assert params["properties"]["title"]["type"] == "string"
        assert params["properties"]["priority"]["type"] == "string"
        assert set(params["properties"]["priority"]["enum"]) == {
            "low",
            "medium",
            "high",
        }
        assert params["properties"]["tags"]["type"] == "array"
        assert params["properties"]["tags"]["items"] == {"type": "string"}
        assert params["properties"]["metadata"]["type"] == "object"

        # Descriptions from docstring
        assert params["properties"]["title"]["description"] == "The task title."
        assert params["properties"]["priority"]["description"] == "Task priority level."

        # All params required (no defaults)
        assert set(params["required"]) == {"title", "priority", "tags", "metadata"}


class TestToolDecoratorCallableExecution:
    @pytest.mark.asyncio
    async def test_tool_decorator_callable_execution(self) -> None:
        """Decorated function can be called and returns correct result."""

        @tool(name="greet", description="Greet")
        def greet(name: str, greeting: str = "Hello") -> str:
            """Greet a person."""
            return f"{greeting}, {name}!"

        td: ToolDefinition = greet.__tool_definition__

        # handler is async-callable (sync wrapped)
        result = await td.handler("Alice")
        assert result == "Hello, Alice!"

        result2 = await td.handler("Bob", greeting="Hi")
        assert result2 == "Hi, Bob!"

    @pytest.mark.asyncio
    async def test_tool_decorator_async_callable_execution(self) -> None:
        """Async decorated function can be called."""

        @tool(name="fetch", description="Fetch")
        async def fetch(url: str) -> str:
            return f"fetched: {url}"

        td: ToolDefinition = fetch.__tool_definition__
        result = await td.handler("https://example.com")
        assert result == "fetched: https://example.com"


class TestToolDecoratorWithRuntimeMock:
    def test_tool_decorator_with_runtime_mock(self) -> None:
        """ThinRuntime accepts tool from @tool — ToolSpec has all required fields."""

        @tool(name="calculator")
        def calc(expression: str) -> str:
            """Evaluate a math expression.

            Args:
                expression: The math expression to evaluate.
            """
            return f"calc: {expression}"

        spec = calc.__tool_definition__.to_tool_spec()

        # Validate ToolSpec has all fields ThinRuntime expects
        assert spec.name
        assert spec.description
        assert isinstance(spec.parameters, dict)
        assert spec.parameters.get("type") == "object"
        assert isinstance(spec.parameters.get("properties"), dict)
        assert spec.is_local is True

        # to_dict() should be serializable
        d = spec.to_dict()
        assert d["name"] == "calculator"
        assert d["description"] == "Evaluate a math expression."
        assert "expression" in d["parameters"]["properties"]
