"""Stage 4 (Sprint 1A): introduce ToolFunction Protocol for @tool-decorated
callables.

Background — `@tool` decorator stamps `__tool_definition__: ToolDefinition`
onto the function object, but the raw `Callable` type does not advertise this
attribute. As a result, `ty` strict reported 4 unresolved-attribute errors:
    agent/tool.py:72                — fn.__tool_definition__ = tool_def
    multi_agent/graph_tools.py:196  — hire_agent.__tool_definition__
    multi_agent/graph_tools.py:197  — delegate_task.__tool_definition__
    multi_agent/graph_tools.py:198  — escalate.__tool_definition__

Fix — declare `ToolFunction` Protocol with `__tool_definition__` attribute and
`cast` decorated functions to it at the boundary. Removes 4 `# type: ignore[attr-defined]`
comments and gives downstream code a typed interface.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from swarmline.agent import ToolFunction, tool
from swarmline.agent.tool import ToolDefinition


def test_tool_function_protocol_exported_from_swarmline_agent() -> None:
    """`ToolFunction` is importable from `swarmline.agent` (top of module).

    Note: identity (`is`) check would be fragile because `test_import_isolation.py`
    deletes `swarmline*` keys from `sys.modules`, causing later re-imports of
    `swarmline.agent.tool_protocol` to produce a *new* class object with the same
    qualified name. Verify the export contract via fully-qualified module + name
    instead — that is what consumers actually rely on.
    """
    import swarmline.agent

    assert hasattr(swarmline.agent, "ToolFunction")
    exported = swarmline.agent.ToolFunction
    assert exported.__module__ == "swarmline.agent.tool_protocol"
    assert exported.__name__ == "ToolFunction"


def test_tool_function_protocol_declares_tool_definition_attribute() -> None:
    """`ToolFunction` Protocol declares `__tool_definition__: ToolDefinition`.

    Verifies via `get_type_hints` so future refactors cannot silently drop the
    attribute and reintroduce ty errors.
    """
    # Use raw __annotations__ — Protocol with `from __future__ import annotations`
    # stores forward-references as strings; get_type_hints fails because
    # ToolDefinition is only TYPE_CHECKING-imported (avoids tool.py↔tool_protocol.py
    # circular import). String check is sufficient as an invariant guard.
    raw_annotations = ToolFunction.__annotations__
    assert "__tool_definition__" in raw_annotations, (
        "ToolFunction Protocol must declare __tool_definition__ attribute"
    )
    annotation_str = raw_annotations["__tool_definition__"]
    # Either string forward-ref ("ToolDefinition") or actual class
    annotation_repr = (
        annotation_str if isinstance(annotation_str, str) else annotation_str.__name__
    )
    assert "ToolDefinition" in annotation_repr, (
        f"Expected ToolDefinition annotation, got {annotation_repr!r}"
    )


def test_decorated_function_satisfies_tool_function_at_runtime() -> None:
    """`@tool`-decorated function satisfies `isinstance(fn, ToolFunction)`."""

    @tool("greet", description="Greet someone.")
    async def greet(name: str) -> str:
        return f"hi {name}"

    assert isinstance(greet, ToolFunction), (
        "Decorated function should satisfy ToolFunction Protocol via @runtime_checkable"
    )
    # Direct attribute access — no type:ignore needed
    assert greet.__tool_definition__.name == "greet"
    assert greet.__tool_definition__.description == "Greet someone."


def test_plain_function_does_not_satisfy_tool_function_protocol() -> None:
    """Negative assertion: undecorated function fails isinstance."""

    async def plain(x: str) -> str:
        return x

    assert not isinstance(plain, ToolFunction), (
        "Plain function (no @tool) should NOT satisfy ToolFunction"
    )


def test_tool_decorator_does_not_use_attr_defined_ignore() -> None:
    """Source-level invariant: agent/tool.py uses cast(ToolFunction, fn) — no
    `# type: ignore[attr-defined]` for __tool_definition__ attribute."""
    import inspect

    from swarmline.agent import tool as tool_module

    source = inspect.getsource(tool_module)
    # Locate the decorator inner closure
    assert "ToolFunction" in source, (
        "agent/tool.py must reference ToolFunction (cast or import). "
        "Did Stage 4 fix regress?"
    )
    # No type:ignore[attr-defined] should remain in the file
    forbidden = "# type: ignore[attr-defined]"
    assert forbidden not in source, (
        f"agent/tool.py must not contain {forbidden!r} after Stage 4 — "
        f"use cast(ToolFunction, fn) instead."
    )


def test_graph_tools_does_not_use_attr_defined_ignore() -> None:
    """Source-level invariant: no `# type: ignore[attr-defined]` on
    `__tool_definition__` access in graph_tools.py.

    Since `tool()` returns `ToolFunction` natively (Stage 4), direct attribute
    access (`hire_agent.__tool_definition__`) is type-safe — no cast needed.
    The earlier silencing comments are obsolete and must not return.
    """
    import inspect

    from swarmline.multi_agent import graph_tools

    source = inspect.getsource(graph_tools)
    forbidden = "# type: ignore[attr-defined]"
    assert forbidden not in source, (
        f"graph_tools.py must not contain {forbidden!r} after Stage 4 — "
        f"`tool()` returns ToolFunction so __tool_definition__ access is "
        f"already typed-safe (no cast needed)."
    )
    # __tool_definition__ access must still happen (smoke test)
    assert "__tool_definition__" in source


@pytest.mark.parametrize(
    "decorator_call",
    [
        ("simple", lambda: tool("simple")),
        ("with-description", lambda: tool("named", description="My tool.")),
    ],
)
def test_tool_decorator_returns_tool_function_compatible(
    decorator_call: tuple[str, Callable[[], Any]],
) -> None:
    """Every variant of `@tool(...)` produces a ToolFunction-compatible object."""
    _label, factory = decorator_call
    decorator = factory()

    async def fn(x: str) -> str:
        return x

    decorated = decorator(fn)
    assert isinstance(decorated, ToolFunction)
    assert isinstance(decorated.__tool_definition__, ToolDefinition)
