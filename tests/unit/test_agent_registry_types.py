"""Unit tests for AgentRegistry domain types and protocol.

Tests cover:
- AgentRecord frozen dataclass (9 fields, immutability)
- AgentStatus enum (exactly 3 values)
- AgentFilter frozen dataclass (3 fields)
- AgentRegistry protocol is runtime_checkable with exactly 5 methods
"""

from __future__ import annotations

import dataclasses

import pytest

from swarmline.multi_agent.registry_types import AgentFilter, AgentRecord, AgentStatus
from swarmline.protocols.multi_agent import AgentRegistry


class TestAgentStatus:
    """AgentStatus enum must have exactly 3 string values."""

    def test_agent_status_values_exactly_three(self) -> None:
        assert len(AgentStatus) == 3

    @pytest.mark.parametrize(
        ("member", "value"),
        [
            (AgentStatus.IDLE, "idle"),
            (AgentStatus.RUNNING, "running"),
            (AgentStatus.STOPPED, "stopped"),
        ],
    )
    def test_agent_status_member_value(self, member: AgentStatus, value: str) -> None:
        assert member.value == value

    def test_agent_status_is_str_subclass(self) -> None:
        assert isinstance(AgentStatus.IDLE, str)


class TestAgentRecord:
    """AgentRecord must be a frozen dataclass with 9 fields."""

    def test_agent_record_is_frozen(self) -> None:
        record = AgentRecord(id="a1", name="Agent1", role="worker")
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.id = "changed"  # type: ignore[misc]

    def test_agent_record_has_nine_fields(self) -> None:
        fields = dataclasses.fields(AgentRecord)
        assert len(fields) == 9

    def test_agent_record_defaults(self) -> None:
        record = AgentRecord(id="a1", name="Agent1", role="worker")
        assert record.parent_id is None
        assert record.runtime_name == "thin"
        assert record.runtime_config == {}
        assert record.status == AgentStatus.IDLE
        assert record.budget_limit_usd is None
        assert record.metadata == {}

    def test_agent_record_all_fields(self) -> None:
        record = AgentRecord(
            id="a1",
            name="Agent1",
            role="researcher",
            parent_id="parent-0",
            runtime_name="claude_sdk",
            runtime_config={"model": "sonnet"},
            status=AgentStatus.RUNNING,
            budget_limit_usd=5.0,
            metadata={"team": "alpha"},
        )
        assert record.id == "a1"
        assert record.name == "Agent1"
        assert record.role == "researcher"
        assert record.parent_id == "parent-0"
        assert record.runtime_name == "claude_sdk"
        assert record.runtime_config == {"model": "sonnet"}
        assert record.status == AgentStatus.RUNNING
        assert record.budget_limit_usd == 5.0
        assert record.metadata == {"team": "alpha"}

    def test_agent_record_is_dataclass(self) -> None:
        assert dataclasses.is_dataclass(AgentRecord)


class TestAgentFilter:
    """AgentFilter must be a frozen dataclass with 3 optional fields."""

    def test_agent_filter_is_frozen(self) -> None:
        filt = AgentFilter()
        with pytest.raises(dataclasses.FrozenInstanceError):
            filt.role = "changed"  # type: ignore[misc]

    def test_agent_filter_has_three_fields(self) -> None:
        fields = dataclasses.fields(AgentFilter)
        assert len(fields) == 3

    def test_agent_filter_defaults_all_none(self) -> None:
        filt = AgentFilter()
        assert filt.role is None
        assert filt.status is None
        assert filt.parent_id is None

    def test_agent_filter_with_values(self) -> None:
        filt = AgentFilter(role="worker", status=AgentStatus.RUNNING, parent_id="p1")
        assert filt.role == "worker"
        assert filt.status == AgentStatus.RUNNING
        assert filt.parent_id == "p1"


class TestAgentRegistryProtocol:
    """AgentRegistry protocol must be runtime_checkable with exactly 5 methods."""

    def test_agent_registry_protocol_runtime_checkable(self) -> None:
        """A class implementing all 5 methods should satisfy isinstance check."""

        class _FakeRegistry:
            async def register(self, record: AgentRecord) -> None:
                pass

            async def get(self, agent_id: str) -> AgentRecord | None:
                return None

            async def list_agents(
                self, filters: AgentFilter | None = None
            ) -> list[AgentRecord]:
                return []

            async def update_status(self, agent_id: str, status: AgentStatus) -> bool:
                return False

            async def remove(self, agent_id: str) -> bool:
                return False

        assert isinstance(_FakeRegistry(), AgentRegistry)

    def test_agent_registry_has_exactly_five_methods(self) -> None:
        protocol_methods = [
            name
            for name in dir(AgentRegistry)
            if not name.startswith("_") and callable(getattr(AgentRegistry, name, None))
        ]
        assert len(protocol_methods) == 5
        assert set(protocol_methods) == {
            "register",
            "get",
            "list_agents",
            "update_status",
            "remove",
        }

    def test_non_implementing_class_not_instance(self) -> None:
        class _Empty:
            pass

        assert not isinstance(_Empty(), AgentRegistry)


class TestReExports:
    """Verify public API re-exports work."""

    def test_multi_agent_init_exports_registry_types(self) -> None:
        from swarmline.multi_agent import AgentFilter as AF
        from swarmline.multi_agent import AgentRecord as AR
        from swarmline.multi_agent import AgentStatus as AS

        assert AF is AgentFilter
        assert AR is AgentRecord
        assert AS is AgentStatus

    def test_protocols_init_exports_agent_registry(self) -> None:
        from swarmline.protocols import AgentRegistry as AR

        assert AR is AgentRegistry
