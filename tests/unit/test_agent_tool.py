"""Unit: @tool decorator + ToolDefinition — standalone tool registration."""

from __future__ import annotations

import pytest
from swarmline.agent.tool import ToolDefinition, tool


class TestToolDecoratorBasic:
    """@tool with name + description."""

    def test_creates_tool_definition(self) -> None:
        @tool(name="greet", description="Greet user")
        async def greet(name: str) -> str:
            return f"Hello, {name}!"

        assert hasattr(greet, "__tool_definition__")
        td: ToolDefinition = greet.__tool_definition__
        assert td.name == "greet"
        assert td.description == "Greet user"

    @pytest.mark.asyncio
    async def test_decorated_function_still_callable(self) -> None:
        """Dekorirovannaya funktsiya vyzyvaetsya as-is."""

        @tool(name="add", description="Add two numbers")
        async def add(a: int, b: int) -> int:
            return a + b

        result = await add(2, 3)
        assert result == 5

    def test_tool_definition_handler_reference(self) -> None:
        """handler in ToolDefinition - ssylka on originalnuyu funktsiyu."""

        @tool(name="echo", description="Echo")
        async def echo(text: str) -> str:
            return text

        td: ToolDefinition = echo.__tool_definition__
        assert td.handler is echo


class TestToolAutoSchema:
    """Auto-infer JSON Schema from type hints."""

    def test_str_param(self) -> None:
        @tool(name="t", description="d")
        async def fn(name: str) -> str:
            return name

        td: ToolDefinition = fn.__tool_definition__
        assert td.parameters["type"] == "object"
        assert td.parameters["properties"]["name"]["type"] == "string"
        assert "name" in td.parameters.get("required", [])

    def test_int_param(self) -> None:
        @tool(name="t", description="d")
        async def fn(count: int) -> int:
            return count

        td: ToolDefinition = fn.__tool_definition__
        assert td.parameters["properties"]["count"]["type"] == "integer"

    def test_float_param(self) -> None:
        @tool(name="t", description="d")
        async def fn(amount: float) -> float:
            return amount

        td: ToolDefinition = fn.__tool_definition__
        assert td.parameters["properties"]["amount"]["type"] == "number"

    def test_bool_param(self) -> None:
        @tool(name="t", description="d")
        async def fn(flag: bool) -> bool:
            return flag

        td: ToolDefinition = fn.__tool_definition__
        assert td.parameters["properties"]["flag"]["type"] == "boolean"

    def test_multiple_params(self) -> None:
        @tool(name="t", description="d")
        async def fn(name: str, age: int, active: bool) -> str:
            return ""

        td: ToolDefinition = fn.__tool_definition__
        props = td.parameters["properties"]
        assert props["name"]["type"] == "string"
        assert props["age"]["type"] == "integer"
        assert props["active"]["type"] == "boolean"
        assert set(td.parameters["required"]) == {"name", "age", "active"}

    def test_optional_param_not_required(self) -> None:
        """Optional parameters not popadayut in required."""

        @tool(name="t", description="d")
        async def fn(name: str, nickname: str | None = None) -> str:
            return name

        td: ToolDefinition = fn.__tool_definition__
        assert "name" in td.parameters["required"]
        assert "nickname" not in td.parameters.get("required", [])

    def test_no_params(self) -> None:
        """Funktsiya without parameterov -> empty schema."""

        @tool(name="t", description="d")
        async def fn() -> str:
            return "ok"

        td: ToolDefinition = fn.__tool_definition__
        assert td.parameters["type"] == "object"
        assert td.parameters["properties"] == {}


class TestToolExplicitSchema:
    """YAvnaya schema vmesto auto-infer."""

    def test_explicit_schema_overrides(self) -> None:
        custom_schema = {
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 200}},
            "required": ["query"],
        }

        @tool(name="search", description="Search", schema=custom_schema)
        async def search(query: str) -> str:
            return query

        td: ToolDefinition = search.__tool_definition__
        assert td.parameters == custom_schema
        assert td.parameters["properties"]["query"]["maxLength"] == 200


class TestToolDefinitionConversion:
    """Conversion ToolDefinition -> SDK/ToolSpec formaty."""

    def test_to_tool_spec(self) -> None:
        """Conversion in swarmline ToolSpec (for thin/deepagents)."""
        from swarmline.runtime.types import ToolSpec

        @tool(name="calc", description="Calculator")
        async def calc(expr: str) -> str:
            return "42"

        td: ToolDefinition = calc.__tool_definition__
        spec = td.to_tool_spec()

        assert isinstance(spec, ToolSpec)
        assert spec.name == "calc"
        assert spec.description == "Calculator"
        assert spec.parameters == td.parameters
        assert spec.is_local is True

    def test_to_tool_spec_preserves_schema(self) -> None:
        @tool(name="t", description="d")
        async def fn(x: int, y: float) -> str:
            return ""

        td: ToolDefinition = fn.__tool_definition__
        spec = td.to_tool_spec()
        assert spec.parameters["properties"]["x"]["type"] == "integer"
        assert spec.parameters["properties"]["y"]["type"] == "number"


class TestToolDefinitionDataclass:
    """ToolDefinition — frozen dataclass."""

    def test_frozen(self) -> None:
        import dataclasses

        @tool(name="t", description="d")
        async def fn() -> str:
            return ""

        td: ToolDefinition = fn.__tool_definition__
        with pytest.raises(dataclasses.FrozenInstanceError):
            td.name = "new"  # type: ignore[misc]


class TestAdaptHandler:
    """_adapt_handler - obertka user handler -> SDK MCP handler contract."""

    @pytest.mark.asyncio
    async def test_adapts_kwargs_and_wraps_result(self) -> None:
        """User handler(a, b) → SDK handler(args_dict) → {content: [...]}."""
        from swarmline.agent.agent import _adapt_handler

        @tool(name="add", description="Add")
        async def add(a: int, b: int) -> int:
            return a + b

        adapted = _adapt_handler(add.__tool_definition__.handler)
        result = await adapted({"a": 2, "b": 3})

        assert isinstance(result, dict)
        assert "content" in result
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "5"

    @pytest.mark.asyncio
    async def test_adapts_string_result(self) -> None:
        from swarmline.agent.agent import _adapt_handler

        @tool(name="greet", description="Greet")
        async def greet(name: str) -> str:
            return f"Hello, {name}!"

        adapted = _adapt_handler(greet.__tool_definition__.handler)
        result = await adapted({"name": "Alice"})

        assert result["content"][0]["text"] == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_handler_returning_dict_passthrough(self) -> None:
        """If handler uzhe returns MCP-format {content: [...]}, not oborachivaem."""
        from swarmline.agent.agent import _adapt_handler

        @tool(name="raw", description="Raw")
        async def raw(x: str) -> dict:
            return {"content": [{"type": "text", "text": "raw result"}]}

        adapted = _adapt_handler(raw.__tool_definition__.handler)
        result = await adapted({"x": "test"})

        assert result["content"][0]["text"] == "raw result"

    @pytest.mark.asyncio
    async def test_handler_error_returns_is_error(self) -> None:
        """If handler brosaet exception -> is_error=True."""
        from swarmline.agent.agent import _adapt_handler

        @tool(name="fail", description="Fail")
        async def fail(x: str) -> str:
            raise ValueError("boom")

        adapted = _adapt_handler(fail.__tool_definition__.handler)
        result = await adapted({"x": "test"})

        assert result.get("is_error") is True
        assert "boom" in result["content"][0]["text"]
