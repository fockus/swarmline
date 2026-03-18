"""@tool decorator + ToolDefinition - standalone tool registration."""

from __future__ import annotations

import asyncio
import enum
import functools
import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, get_args, get_origin

from cognitia.runtime.types import ToolSpec

# Mapping Python types -> JSON Schema types
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


@dataclass(frozen=True)
class ToolDefinition:
    """Tool description created via @tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[Any]]

    def to_tool_spec(self) -> ToolSpec:
        """Convert to cognitia ToolSpec (for thin/deepagents runtime)."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            is_local=True,
        )


def tool(
    name: str,
    description: str | None = None,
    *,
    schema: dict[str, Any] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Standalone decorator for defining tools.

    Args:
        name: unique tool name.
        description: description for the LLM. If None, it is taken from the docstring.
        schema: explicit JSON Schema (if None, auto-inferred from type hints).

    Returns:
        Decorator that adds __tool_definition__ to the function.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        resolved_desc = description if description is not None else _extract_description(fn)
        params = schema if schema is not None else _infer_schema(fn)
        handler = _ensure_async(fn)

        tool_def = ToolDefinition(
            name=name,
            description=resolved_desc,
            parameters=params,
            handler=handler,
        )
        fn.__tool_definition__ = tool_def  # type: ignore[attr-defined]
        return fn

    return decorator


def _ensure_async(fn: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
    """Wrap a sync function into async if needed."""
    if asyncio.iscoroutinefunction(fn):
        return fn

    @functools.wraps(fn)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)

    return async_wrapper


def _extract_description(fn: Callable[..., Any]) -> str:
    """Extract the description from a function docstring (first non-empty line)."""
    doc = inspect.getdoc(fn)
    if not doc:
        return ""
    first_line = doc.strip().split("\n")[0].strip()
    return first_line


def _parse_google_docstring_args(fn: Callable[..., Any]) -> dict[str, str]:
    """Parse the Google-style Args section from a docstring.

    Returns:
        Dict mapping param name to its description.
    """
    doc = inspect.getdoc(fn)
    if not doc:
        return {}

    # Find the "Args:" section
    args_match = re.search(r"^Args:\s*$", doc, re.MULTILINE)
    if not args_match:
        return {}

    args_text = doc[args_match.end() :]

    # Parse until the next section (line starting without indent) or end
    result: dict[str, str] = {}
    current_param: str | None = None
    current_desc_lines: list[str] = []

    for line in args_text.split("\n"):
        # Empty line or new section header (no leading whitespace) -> stop
        stripped = line.strip()
        if not stripped:
            continue

        # Check if the line starts a new section (non-indented, ends with ":")
        if line and not line[0].isspace() and stripped.endswith(":"):
            break

        # Non-indented non-section line -> stop
        if line and not line[0].isspace():
            break

        # Parameter line: "    param_name: description" or "    param_name (type): description"
        param_match = re.match(r"^\s{4}(\w+)(?:\s*\([^)]*\))?\s*:\s*(.*)$", line)
        if param_match:
            # Save previous param
            if current_param is not None:
                result[current_param] = " ".join(current_desc_lines).strip()
            current_param = param_match.group(1)
            current_desc_lines = [param_match.group(2).strip()] if param_match.group(2).strip() else []
        elif current_param is not None and stripped:
            # Continuation line for the current param
            current_desc_lines.append(stripped)

    # Save last param
    if current_param is not None:
        result[current_param] = " ".join(current_desc_lines).strip()

    return result


def _infer_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Auto-infer JSON Schema from function type hints.

    Supports: str, int, float, bool, list[T], dict, Optional[T], T | None,
    Enum subclasses, Pydantic BaseModel subclasses.
    Parses Google-style docstrings for parameter descriptions.
    """
    sig = inspect.signature(fn)
    hints = _get_resolved_hints(fn)
    docstring_args = _parse_google_docstring_args(fn)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls", "return"):
            continue

        annotation = hints.get(param_name, inspect.Parameter.empty)

        # No type hint -> fallback to string
        if annotation is inspect.Parameter.empty:
            prop: dict[str, Any] = {"type": "string"}
            if param_name in docstring_args:
                prop["description"] = docstring_args[param_name]
            properties[param_name] = prop
            if param.default is inspect.Parameter.empty:
                required.append(param_name)
            continue

        is_optional = _is_optional(annotation)
        prop = _resolve_type_to_schema(annotation)

        # Add docstring description
        if param_name in docstring_args:
            prop["description"] = docstring_args[param_name]

        properties[param_name] = prop

        if not is_optional and param.default is inspect.Parameter.empty:
            required.append(param_name)

    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        result["required"] = required
    return result


def _get_resolved_hints(fn: Callable[..., Any]) -> dict[str, Any]:
    """Get resolved type hints (strings -> real types)."""
    try:
        import typing

        return typing.get_type_hints(fn)
    except Exception:
        return getattr(fn, "__annotations__", {})


def _resolve_type_to_schema(annotation: Any) -> dict[str, Any]:
    """Resolve a Python type annotation to a JSON Schema dict."""
    # Direct scalar mapping
    if annotation in _TYPE_MAP:
        return {"type": _TYPE_MAP[annotation]}

    # Optional[T] = Union[T, None] -> unwrap inner type
    if _is_optional(annotation):
        args = get_args(annotation)
        for arg in args:
            if arg is not type(None):
                return _resolve_type_to_schema(arg)

    # Enum subclass -> string with enum values
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return {
            "type": "string",
            "enum": [member.value for member in annotation],
        }

    # Pydantic BaseModel subclass
    try:
        from pydantic import BaseModel

        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation.model_json_schema()
    except ImportError:
        pass

    origin = get_origin(annotation)

    # list / List[T]
    if origin is list or annotation is list:
        args = get_args(annotation)
        if args:
            inner = _resolve_type_to_schema(args[0])
            return {"type": "array", "items": inner}
        return {"type": "array"}

    # dict / Dict[K, V]
    if origin is dict or annotation is dict:
        return {"type": "object"}

    # Fallback
    return {"type": "string"}


def _resolve_type(annotation: Any) -> str | None:
    """Resolve a Python type to a JSON Schema type string.

    Backward-compatible wrapper. Returns simple type string.
    """
    schema = _resolve_type_to_schema(annotation)
    return schema.get("type")


def _is_optional(annotation: Any) -> bool:
    """Check whether the type is Optional (Union[T, None] or T | None)."""
    origin = get_origin(annotation)

    # typing.Union or types.UnionType (Python 3.10+ X | Y)
    if origin is not None:
        import types

        if origin is getattr(types, "UnionType", None) or str(origin) == "typing.Union":
            args = get_args(annotation)
            return type(None) in args

    return False
