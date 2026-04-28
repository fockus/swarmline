"""Integration tests for Agent-as-Tool (Phase 9A).

Tests cross-module interactions: spec creation -> execution -> result,
import paths, protocol compliance, and error propagation.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from swarmline.multi_agent.agent_tool import create_agent_tool_spec, execute_agent_tool
from swarmline.multi_agent.types import AgentToolResult
from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent, ToolSpec
import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers — fake run_fn implementations for integration scenarios
# ---------------------------------------------------------------------------


async def _run_fn_echo(
    *,
    messages: list[Any],
    system_prompt: str,
    active_tools: list[Any],
) -> AsyncIterator[RuntimeEvent]:
    """Echo back the user query as final text."""
    user_query = messages[0].content if messages else ""
    yield RuntimeEvent.final(text=f"echo: {user_query}")


async def _run_fn_raises(
    *,
    messages: list[Any],
    system_prompt: str,
    active_tools: list[Any],
) -> AsyncIterator[RuntimeEvent]:
    """Simulate a runtime crash."""
    raise ConnectionError("upstream provider unavailable")
    yield  # noqa: B027 — make it an async generator


async def _run_fn_error_event(
    *,
    messages: list[Any],
    system_prompt: str,
    active_tools: list[Any],
) -> AsyncIterator[RuntimeEvent]:
    """Simulate a runtime that reports failure via RuntimeEvent.error."""
    yield RuntimeEvent.error(
        RuntimeErrorData(kind="runtime_crash", message="provider returned error event")
    )


async def _run_fn_no_final(
    *,
    messages: list[Any],
    system_prompt: str,
    active_tools: list[Any],
) -> AsyncIterator[RuntimeEvent]:
    """Simulate a stream that ends without finalization."""
    yield RuntimeEvent.status("starting")


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestAgentToolSpecRoundtrip:
    """Spec creation feeds into execute_agent_tool end-to-end."""

    async def test_agent_tool_spec_roundtrip_creates_spec_and_executes(self) -> None:
        # Arrange — create spec and verify structure
        spec = create_agent_tool_spec("researcher", "Deep research sub-agent")
        assert isinstance(spec, ToolSpec)
        assert spec.name == "researcher"
        assert "query" in spec.parameters["properties"]
        assert "query" in spec.parameters["required"]

        # Act — use the same query param name from the spec to call execute
        query_text = "What are the latest papers on RLHF?"
        result = await execute_agent_tool(
            run_fn=_run_fn_echo,
            query=query_text,
        )

        # Assert — successful round-trip
        assert isinstance(result, AgentToolResult)
        assert result.success is True
        assert result.output == f"echo: {query_text}"
        assert result.error is None


class TestAgentToolCrossModuleImports:
    """All agent-tool types importable from canonical module paths."""

    def test_agent_tool_cross_module_imports_from_multi_agent(self) -> None:
        # Arrange/Act — import from swarmline.multi_agent
        from swarmline.multi_agent import (
            AgentToolResult as MAResult,
            create_agent_tool_spec as ma_create,
            execute_agent_tool as ma_execute,
        )

        # Assert — same objects as direct imports
        assert MAResult is AgentToolResult
        assert ma_create is create_agent_tool_spec
        assert ma_execute is execute_agent_tool

    def test_agent_tool_cross_module_imports_from_protocols(self) -> None:
        # Arrange/Act — import AgentTool protocol from swarmline.protocols
        from swarmline.protocols import AgentTool
        from swarmline.protocols.multi_agent import AgentTool as DirectAgentTool

        # Assert — same protocol class
        assert AgentTool is DirectAgentTool

    def test_agent_tool_cross_module_imports_toolspec_consistent(self) -> None:
        # Arrange/Act — ToolSpec used in agent_tool.py matches runtime.types
        from swarmline.runtime.types import ToolSpec as RTToolSpec

        spec = create_agent_tool_spec("test", "test agent")

        # Assert — same class
        assert type(spec) is RTToolSpec


class TestAgentToolProtocolCompliance:
    """Custom class implementing AgentTool passes isinstance check."""

    def test_agent_tool_protocol_compliance_isinstance_check(self) -> None:
        # Arrange — import the protocol
        from swarmline.protocols import AgentTool

        # Arrange — create a class that implements as_tool()
        class MyAgentWrapper:
            def as_tool(self, name: str, description: str) -> ToolSpec:
                return create_agent_tool_spec(name, description)

        # Act
        wrapper = MyAgentWrapper()

        # Assert — runtime_checkable isinstance passes
        assert isinstance(wrapper, AgentTool)

    def test_agent_tool_protocol_compliance_as_tool_returns_valid_spec(self) -> None:
        # Arrange
        class MyAgentWrapper:
            def as_tool(self, name: str, description: str) -> ToolSpec:
                return create_agent_tool_spec(name, description)

        wrapper = MyAgentWrapper()

        # Act
        spec = wrapper.as_tool("summarizer", "Summarization agent")

        # Assert — returned spec is valid ToolSpec with expected shape
        assert isinstance(spec, ToolSpec)
        assert spec.name == "summarizer"
        assert spec.is_local is True

    def test_agent_tool_protocol_compliance_non_conforming_fails(self) -> None:
        # Arrange — class without as_tool
        from swarmline.protocols import AgentTool

        class NotAnAgent:
            pass

        # Act / Assert
        assert not isinstance(NotAnAgent(), AgentTool)


class TestAgentToolExecuteErrorPropagation:
    """Runtime exceptions propagate as AgentToolResult(success=False)."""

    async def test_agent_tool_execute_error_propagation_connection_error(self) -> None:
        # Arrange — run_fn that raises ConnectionError

        # Act
        result = await execute_agent_tool(
            run_fn=_run_fn_raises,
            query="this will fail",
        )

        # Assert — failure with error message preserved
        assert isinstance(result, AgentToolResult)
        assert result.success is False
        assert result.output == ""
        assert result.error is not None
        assert "upstream provider unavailable" in result.error

    async def test_agent_tool_execute_error_propagation_runtime_error(self) -> None:
        # Arrange — inline run_fn with RuntimeError
        async def _run_fn_runtime_error(
            *,
            messages: list[Any],
            system_prompt: str,
            active_tools: list[Any],
        ) -> AsyncIterator[RuntimeEvent]:
            raise RuntimeError("internal agent failure")
            yield  # noqa: B027

        # Act
        result = await execute_agent_tool(
            run_fn=_run_fn_runtime_error,
            query="boom",
        )

        # Assert
        assert result.success is False
        assert "internal agent failure" in (result.error or "")

    async def test_agent_tool_execute_error_propagation_preserves_type_info(
        self,
    ) -> None:
        # Arrange — TypeError from run_fn
        async def _run_fn_type_error(
            *,
            messages: list[Any],
            system_prompt: str,
            active_tools: list[Any],
        ) -> AsyncIterator[RuntimeEvent]:
            raise TypeError("unexpected argument type")
            yield  # noqa: B027

        # Act
        result = await execute_agent_tool(
            run_fn=_run_fn_type_error,
            query="test",
        )

        # Assert — error string contains the original message
        assert result.success is False
        assert result.error == "unexpected argument type"

    async def test_agent_tool_execute_error_event_returns_failure(self) -> None:
        result = await execute_agent_tool(
            run_fn=_run_fn_error_event,
            query="event failure",
        )

        assert result.success is False
        assert result.output == ""
        assert result.error == "provider returned error event"

    async def test_agent_tool_execute_missing_final_returns_failure(self) -> None:
        result = await execute_agent_tool(
            run_fn=_run_fn_no_final,
            query="missing final",
        )

        assert result.success is False
        assert result.output == ""
        assert result.error == "Sub-agent runtime ended without a final event"
