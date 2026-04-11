"""Contract tests for AgentTool Protocol.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing as_tool(name, description) -> ToolSpec should pass.
"""

from __future__ import annotations

from swarmline.runtime.types import ToolSpec


class _ValidAgentTool:
    """Minimal valid implementation for contract testing."""

    def as_tool(self, name: str, description: str) -> ToolSpec:
        return ToolSpec(
            name=name,
            description=description,
            parameters={"type": "object", "properties": {"input": {"type": "string"}}},
            is_local=True,
        )


class _InvalidAgentTool:
    """Class without as_tool method -- should NOT satisfy Protocol."""

    pass


class TestAgentToolProtocol:
    """AgentTool Protocol contract tests."""

    def test_agent_tool_protocol_is_runtime_checkable(self) -> None:
        from swarmline.protocols.multi_agent import AgentTool

        impl = _ValidAgentTool()
        assert isinstance(impl, AgentTool)

    def test_agent_tool_as_tool_returns_tool_spec(self) -> None:
        impl = _ValidAgentTool()
        spec = impl.as_tool("helper", "A helper agent")
        assert isinstance(spec, ToolSpec)
        assert spec.name == "helper"
        assert spec.description == "A helper agent"
        assert "properties" in spec.parameters

    def test_agent_tool_as_tool_marks_local(self) -> None:
        impl = _ValidAgentTool()
        spec = impl.as_tool("sub", "Sub agent")
        assert spec.is_local is True

    def test_agent_tool_without_method_fails_isinstance(self) -> None:
        from swarmline.protocols.multi_agent import AgentTool

        invalid = _InvalidAgentTool()
        assert not isinstance(invalid, AgentTool)

    def test_agent_tool_importable_from_protocols_package(self) -> None:
        from swarmline.protocols import AgentTool

        assert AgentTool is not None
