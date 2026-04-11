"""Tests for execute_agent_tool and create_agent_tool_spec."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from swarmline.multi_agent.agent_tool import create_agent_tool_spec, execute_agent_tool
from swarmline.multi_agent.types import AgentToolResult
from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent, ToolSpec


# ---------------------------------------------------------------------------
# Helpers — fake run_fn implementations
# ---------------------------------------------------------------------------


async def _fake_run_success(
    *, messages: list[Any], system_prompt: str, active_tools: list[Any]
) -> AsyncIterator[RuntimeEvent]:
    yield RuntimeEvent.status("thinking...")
    yield RuntimeEvent.final(text="The answer is 42.")


async def _fake_run_error(
    *, messages: list[Any], system_prompt: str, active_tools: list[Any]
) -> AsyncIterator[RuntimeEvent]:
    raise ValueError("model exploded")
    yield  # noqa: B027 — make it an async generator


class _CustomRuntimeError(Exception):
    """Custom runtime error used to verify broad exception isolation."""


async def _fake_run_key_error(
    *, messages: list[Any], system_prompt: str, active_tools: list[Any]
) -> AsyncIterator[RuntimeEvent]:
    raise KeyError("missing payload")
    yield  # noqa: B027 — make it an async generator


async def _fake_run_custom_error(
    *, messages: list[Any], system_prompt: str, active_tools: list[Any]
) -> AsyncIterator[RuntimeEvent]:
    raise _CustomRuntimeError("custom runtime failure")
    yield  # noqa: B027 — make it an async generator


async def _fake_run_slow(
    *, messages: list[Any], system_prompt: str, active_tools: list[Any]
) -> AsyncIterator[RuntimeEvent]:
    await asyncio.sleep(10)
    yield RuntimeEvent.final(text="too late")


async def _fake_run_empty_final(
    *, messages: list[Any], system_prompt: str, active_tools: list[Any]
) -> AsyncIterator[RuntimeEvent]:
    yield RuntimeEvent.final(text="")


async def _fake_run_error_event(
    *, messages: list[Any], system_prompt: str, active_tools: list[Any]
) -> AsyncIterator[RuntimeEvent]:
    yield RuntimeEvent.error(
        RuntimeErrorData(
            kind="runtime_crash",
            message="runtime emitted error event",
        )
    )


async def _fake_run_no_final(
    *, messages: list[Any], system_prompt: str, active_tools: list[Any]
) -> AsyncIterator[RuntimeEvent]:
    yield RuntimeEvent.status("still thinking")


# ---------------------------------------------------------------------------
# execute_agent_tool tests
# ---------------------------------------------------------------------------


class TestExecuteAgentToolSuccess:
    """Happy path: run_fn yields a final event with text."""

    async def test_execute_agent_tool_success_returns_output(self) -> None:
        result = await execute_agent_tool(
            run_fn=_fake_run_success,
            query="What is the meaning of life?",
        )
        assert isinstance(result, AgentToolResult)
        assert result.success is True
        assert result.output == "The answer is 42."
        assert result.error is None

    async def test_execute_agent_tool_success_custom_system_prompt(self) -> None:
        result = await execute_agent_tool(
            run_fn=_fake_run_success,
            query="test",
            system_prompt="You are a math tutor.",
        )
        assert result.success is True

    async def test_execute_agent_tool_success_empty_output(self) -> None:
        result = await execute_agent_tool(
            run_fn=_fake_run_empty_final,
            query="test",
        )
        assert result.success is True
        assert result.output == ""


class TestExecuteAgentToolError:
    """run_fn raises an exception -> error result."""

    async def test_execute_agent_tool_error_returns_failure(self) -> None:
        result = await execute_agent_tool(
            run_fn=_fake_run_error,
            query="boom",
        )
        assert isinstance(result, AgentToolResult)
        assert result.success is False
        assert result.output == ""
        assert "model exploded" in (result.error or "")

    async def test_execute_agent_tool_error_event_returns_failure(self) -> None:
        result = await execute_agent_tool(
            run_fn=_fake_run_error_event,
            query="boom",
        )

        assert result.success is False
        assert result.output == ""
        assert result.error == "runtime emitted error event"

    async def test_execute_agent_tool_missing_final_returns_failure(self) -> None:
        result = await execute_agent_tool(
            run_fn=_fake_run_no_final,
            query="boom",
        )

        assert result.success is False
        assert result.output == ""
        assert result.error == "Sub-agent runtime ended without a final event"

    async def test_execute_agent_tool_key_error_returns_failure(self) -> None:
        result = await execute_agent_tool(
            run_fn=_fake_run_key_error,
            query="boom",
        )

        assert result.success is False
        assert result.output == ""
        assert "missing payload" in (result.error or "")

    async def test_execute_agent_tool_custom_exception_returns_failure(self) -> None:
        result = await execute_agent_tool(
            run_fn=_fake_run_custom_error,
            query="boom",
        )

        assert result.success is False
        assert result.output == ""
        assert result.error == "custom runtime failure"


class TestExecuteAgentToolTimeout:
    """run_fn takes too long -> timeout error."""

    async def test_execute_agent_tool_timeout_returns_failure(self) -> None:
        result = await execute_agent_tool(
            run_fn=_fake_run_slow,
            query="slow query",
            timeout_seconds=0.05,
        )
        assert isinstance(result, AgentToolResult)
        assert result.success is False
        assert result.output == ""
        assert result.error is not None
        assert "timeout" in result.error.lower()


# ---------------------------------------------------------------------------
# create_agent_tool_spec tests
# ---------------------------------------------------------------------------


class TestCreateAgentToolSpec:
    """create_agent_tool_spec builds a valid ToolSpec."""

    def test_create_agent_tool_spec_name_and_description(self) -> None:
        spec = create_agent_tool_spec("researcher", "Research sub-agent")
        assert isinstance(spec, ToolSpec)
        assert spec.name == "researcher"
        assert spec.description == "Research sub-agent"

    def test_create_agent_tool_spec_has_query_parameter(self) -> None:
        spec = create_agent_tool_spec("writer", "Writing agent")
        props = spec.parameters.get("properties", {})
        assert "query" in props
        assert props["query"]["type"] == "string"

    def test_create_agent_tool_spec_query_is_required(self) -> None:
        spec = create_agent_tool_spec("coder", "Coding agent")
        assert "query" in spec.parameters.get("required", [])

    def test_create_agent_tool_spec_is_local(self) -> None:
        spec = create_agent_tool_spec("helper", "Helper agent")
        assert spec.is_local is True

    def test_create_agent_tool_spec_importable_from_multi_agent(self) -> None:
        from swarmline.multi_agent import create_agent_tool_spec as imported_fn

        assert imported_fn is create_agent_tool_spec

    def test_execute_agent_tool_importable_from_multi_agent(self) -> None:
        from swarmline.multi_agent import execute_agent_tool as imported_fn

        assert imported_fn is execute_agent_tool
