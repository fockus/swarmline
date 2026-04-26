"""Unit: @tool decorator — schema auto-generation, docstring parsing, extended types."""

from __future__ import annotations

import enum

import pytest
from pydantic import BaseModel

from swarmline.agent.tool import ToolDefinition, tool


# --- Fixtures / helpers ---


class Color(enum.Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class Address(BaseModel):
    street: str
    city: str
    zip_code: str


# --- Basic type mapping ---


class TestToolBasicStrParam:
    def test_tool_basic_str_param(self) -> None:
        """def fn(query: str) produces correct schema with string type."""

        @tool(name="search", description="Search")
        async def fn(query: str) -> str:
            return query

        td: ToolDefinition = fn.__tool_definition__
        assert td.parameters["properties"]["query"]["type"] == "string"
        assert "query" in td.parameters["required"]


class TestToolIntFloatBoolParams:
    def test_tool_int_float_bool_params(self) -> None:
        """Multiple typed params produce correct JSON Schema types."""

        @tool(name="calc", description="Calc")
        async def fn(count: int, price: float, active: bool) -> str:
            return ""

        td: ToolDefinition = fn.__tool_definition__
        props = td.parameters["properties"]
        assert props["count"]["type"] == "integer"
        assert props["price"]["type"] == "number"
        assert props["active"]["type"] == "boolean"
        assert set(td.parameters["required"]) == {"count", "price", "active"}


class TestToolListType:
    def test_tool_list_type(self) -> None:
        """list[str] produces array schema with items."""

        @tool(name="t", description="d")
        async def fn(tags: list[str]) -> str:
            return ""

        td: ToolDefinition = fn.__tool_definition__
        prop = td.parameters["properties"]["tags"]
        assert prop["type"] == "array"
        assert prop["items"] == {"type": "string"}

    def test_tool_list_int(self) -> None:
        """list[int] produces array with integer items."""

        @tool(name="t", description="d")
        async def fn(ids: list[int]) -> str:
            return ""

        td: ToolDefinition = fn.__tool_definition__
        prop = td.parameters["properties"]["ids"]
        assert prop["type"] == "array"
        assert prop["items"] == {"type": "integer"}

    def test_tool_bare_list(self) -> None:
        """Bare list (no type arg) produces array without items."""

        @tool(name="t", description="d")
        async def fn(data: list) -> str:
            return ""

        td: ToolDefinition = fn.__tool_definition__
        prop = td.parameters["properties"]["data"]
        assert prop["type"] == "array"


class TestToolDictType:
    def test_tool_dict_type(self) -> None:
        """dict produces object schema."""

        @tool(name="t", description="d")
        async def fn(metadata: dict) -> str:
            return ""

        td: ToolDefinition = fn.__tool_definition__
        assert td.parameters["properties"]["metadata"]["type"] == "object"

    def test_tool_dict_with_type_args(self) -> None:
        """dict[str, int] produces object schema."""

        @tool(name="t", description="d")
        async def fn(scores: dict[str, int]) -> str:
            return ""

        td: ToolDefinition = fn.__tool_definition__
        assert td.parameters["properties"]["scores"]["type"] == "object"


class TestToolOptionalParam:
    def test_tool_optional_param(self) -> None:
        """Optional[str] is not in required list."""

        @tool(name="t", description="d")
        async def fn(name: str, nickname: str | None = None) -> str:
            return name

        td: ToolDefinition = fn.__tool_definition__
        assert "name" in td.parameters["required"]
        assert "nickname" not in td.parameters.get("required", [])
        # Optional[str] still has string type
        assert td.parameters["properties"]["nickname"]["type"] == "string"

    def test_tool_union_none_syntax(self) -> None:
        """str | None is treated as optional."""

        @tool(name="t", description="d")
        async def fn(title: str | None = None) -> str:
            return ""

        td: ToolDefinition = fn.__tool_definition__
        assert "title" not in td.parameters.get("required", [])


class TestToolDefaultValueNotRequired:
    def test_tool_default_value_not_required(self) -> None:
        """Param with default value is not required even without Optional."""

        @tool(name="t", description="d")
        async def fn(query: str, limit: int = 10) -> str:
            return query

        td: ToolDefinition = fn.__tool_definition__
        assert "query" in td.parameters["required"]
        assert "limit" not in td.parameters.get("required", [])


class TestToolEnumParam:
    def test_tool_enum_param(self) -> None:
        """Enum type produces string schema with enum values."""

        @tool(name="t", description="d")
        async def fn(color: Color) -> str:
            return color.value

        td: ToolDefinition = fn.__tool_definition__
        prop = td.parameters["properties"]["color"]
        assert prop["type"] == "string"
        assert set(prop["enum"]) == {"red", "green", "blue"}
        assert "color" in td.parameters["required"]


class TestToolPydanticModelParam:
    def test_tool_pydantic_model_param(self) -> None:
        """BaseModel param produces model_json_schema() output."""

        @tool(name="t", description="d")
        async def fn(address: Address) -> str:
            return address.city

        td: ToolDefinition = fn.__tool_definition__
        prop = td.parameters["properties"]["address"]
        # Should contain the Pydantic model schema
        assert prop["type"] == "object"
        assert "street" in prop["properties"]
        assert "city" in prop["properties"]
        assert "zip_code" in prop["properties"]


class TestToolGoogleDocstringDescriptions:
    def test_tool_google_docstring_descriptions(self) -> None:
        """Google-style Args section provides param descriptions."""

        @tool(name="t", description="d")
        async def fn(query: str, limit: int = 10) -> str:
            """Search for items.

            Args:
                query: The search query string.
                limit: Maximum number of results.
            """
            return query

        td: ToolDefinition = fn.__tool_definition__
        assert (
            td.parameters["properties"]["query"]["description"]
            == "The search query string."
        )
        assert (
            td.parameters["properties"]["limit"]["description"]
            == "Maximum number of results."
        )


class TestToolAutoDescriptionFromDocstring:
    def test_tool_auto_description_from_docstring(self) -> None:
        """First line of docstring used as description when not explicit."""

        @tool(name="t")
        async def fn(query: str) -> str:
            """Search for items in the database."""
            return query

        td: ToolDefinition = fn.__tool_definition__
        assert td.description == "Search for items in the database."

    def test_tool_auto_description_multiline_docstring(self) -> None:
        """Only first non-empty line used."""

        @tool(name="t")
        async def fn(query: str) -> str:
            """Search for items.

            This is a longer description that should not be used.
            """
            return query

        td: ToolDefinition = fn.__tool_definition__
        assert td.description == "Search for items."


class TestToolExplicitDescriptionOverrides:
    def test_tool_explicit_description_overrides(self) -> None:
        """Explicit description takes priority over docstring."""

        @tool(name="t", description="Explicit desc")
        async def fn(query: str) -> str:
            """Docstring desc."""
            return query

        td: ToolDefinition = fn.__tool_definition__
        assert td.description == "Explicit desc"


class TestToolNoHintsFallback:
    def test_tool_no_hints_fallback(self) -> None:
        """No type annotations fallback to string type."""

        @tool(name="t", description="d")
        async def fn(query) -> str:  # noqa: ANN001
            return str(query)

        td: ToolDefinition = fn.__tool_definition__
        assert td.parameters["properties"]["query"]["type"] == "string"
        assert "query" in td.parameters["required"]


class TestToolNoDocstring:
    def test_tool_no_docstring(self) -> None:
        """No docstring produces empty description."""

        @tool(name="t")
        async def fn(query: str) -> str:
            return query

        td: ToolDefinition = fn.__tool_definition__
        assert td.description == ""


class TestToolAsyncFunction:
    @pytest.mark.asyncio
    async def test_tool_async_function(self) -> None:
        """Async function works correctly."""

        @tool(name="t", description="d")
        async def fn(query: str) -> str:
            return f"result: {query}"

        result = await fn("test")
        assert result == "result: test"
        assert hasattr(fn, "__tool_definition__")


class TestToolSyncFunction:
    @pytest.mark.asyncio
    async def test_tool_sync_function(self) -> None:
        """Sync function is auto-wrapped to async."""

        @tool(name="t", description="d")
        def fn(query: str) -> str:
            return f"result: {query}"

        td: ToolDefinition = fn.__tool_definition__
        # handler should be async-callable
        result = await td.handler("test")
        assert result == "result: test"

    def test_tool_sync_function_schema(self) -> None:
        """Sync function schema is correctly inferred."""

        @tool(name="t", description="d")
        def fn(name: str, age: int) -> str:
            return f"{name} {age}"

        td: ToolDefinition = fn.__tool_definition__
        assert td.parameters["properties"]["name"]["type"] == "string"
        assert td.parameters["properties"]["age"]["type"] == "integer"
        assert set(td.parameters["required"]) == {"name", "age"}
