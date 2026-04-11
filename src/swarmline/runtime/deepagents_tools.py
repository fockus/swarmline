"""LangChain tool wrappers for DeepAgents runtime."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from swarmline.runtime.types import ToolSpec


def create_langchain_tool(spec: ToolSpec, executor: Callable | None = None) -> Any:
    """Create langchain tool."""
    from langchain_core.tools import StructuredTool

    schema = dict(spec.parameters or {})
    schema.setdefault("title", f"{spec.name}Input")
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    schema.setdefault("additionalProperties", True)

    async def _noop(**kwargs: Any) -> str:
        return json.dumps({"error": f"Tool {spec.name} не имеет executor"})

    async def _call_executor(**kwargs: Any) -> str:
        if executor is None:
            return await _noop(**kwargs)

        try:
            result = executor(**kwargs)
        except TypeError:
            result = executor(kwargs)

        if hasattr(result, "__await__"):
            result = await result

        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    return StructuredTool.from_function(
        coroutine=_call_executor,
        name=spec.name,
        description=spec.description,
        args_schema=schema,
        infer_schema=False,
    )
