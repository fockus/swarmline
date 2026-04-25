"""ToolFunction Protocol — typed contract for `@tool`-decorated callables.

Background — `swarmline.agent.tool.tool()` decorates a `Callable[..., Any]`
and stamps `__tool_definition__: ToolDefinition` onto it. The raw `Callable`
type does not advertise this attribute; without an explicit Protocol, type
checkers (`ty` strict mode) flag every read of `fn.__tool_definition__` as
`unresolved-attribute`. Prior workaround was `# type: ignore[attr-defined]`
at every call site — fragile and type-hostile.

This Protocol declares the post-decoration contract. Use:

    decorated = tool("greet")(my_func)
    assert isinstance(decorated, ToolFunction)        # runtime_checkable
    print(decorated.__tool_definition__.name)         # typed access

Or, when the type checker needs explicit narrowing:

    from typing import cast
    spec = cast(ToolFunction, my_decorated_func).__tool_definition__

ISP-aligned: 1 attribute + 1 callable surface = narrow Protocol, easy to
implement (concrete decorator does it automatically).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from swarmline.agent.tool import ToolDefinition


@runtime_checkable
class ToolFunction(Protocol):
    """Callable enriched by `@tool` decorator with `__tool_definition__`.

    Concrete instances are produced by `swarmline.agent.tool.tool(...)`.
    Backends (ThinRuntime, ClaudeCodeRuntime, DeepAgentsRuntime) consume the
    `.__tool_definition__` attribute to register tools with the underlying LLM.
    """

    __tool_definition__: ToolDefinition

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
