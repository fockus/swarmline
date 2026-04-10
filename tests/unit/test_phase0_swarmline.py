"""Comprehensive tests for Phase 0 (Swarmline) components.

Covers: LifecycleMode, AgentNode, AgentCapabilities, GraphBuilder,
Governance, HostAdapter Protocol, AgentSDKAdapter, CodexAdapter,
GoalQueue, ModelRegistry, Orchestrator lifecycle.
"""

from __future__ import annotations

import dataclasses
from typing import Any
from unittest.mock import AsyncMock

import pytest

from cognitia.multi_agent.goal_queue import GoalQueue, GoalStatus
from cognitia.multi_agent.graph_builder import GraphBuilder
from cognitia.multi_agent.graph_governance import (
    GraphGovernanceConfig,
    check_authority_delegation,
    check_hire_allowed,
    validate_capability_delegation,
)
from cognitia.multi_agent.graph_store import InMemoryAgentGraph
from cognitia.multi_agent.graph_types import AgentCapabilities, AgentNode, LifecycleMode
from cognitia.protocols.host_adapter import AgentAuthority, AgentHandle, AgentHandleStatus, HostAdapter
from cognitia.runtime.agent_sdk_adapter import AgentSDKAdapter
from cognitia.runtime.codex_adapter import CodexAdapter
from cognitia.runtime.model_registry import get_registry, reset_registry


# ============================================================
# 1. LifecycleMode + AgentNode
# ============================================================


class TestLifecycleMode:
    @pytest.mark.parametrize(
        ("member", "value"),
        [
            (LifecycleMode.EPHEMERAL, "ephemeral"),
            (LifecycleMode.SUPERVISED, "supervised"),
            (LifecycleMode.PERSISTENT, "persistent"),
        ],
    )
    def test_lifecycle_mode_values(self, member: LifecycleMode, value: str) -> None:
        assert member.value == value

    def test_lifecycle_mode_has_exactly_three_members(self) -> None:
        assert len(LifecycleMode) == 3


class TestAgentNode:
    def test_default_lifecycle_is_supervised(self) -> None:
        node = AgentNode(id="a", name="A", role="dev")
        assert node.lifecycle == LifecycleMode.SUPERVISED

    def test_node_with_hooks_and_lifecycle(self) -> None:
        node = AgentNode(
            id="a",
            name="A",
            role="dev",
            lifecycle=LifecycleMode.EPHEMERAL,
            hooks=("hook1", "hook2"),
        )
        assert node.lifecycle == LifecycleMode.EPHEMERAL
        assert node.hooks == ("hook1", "hook2")

    def test_frozen_dataclass_immutability(self) -> None:
        node = AgentNode(id="a", name="A", role="dev")
        with pytest.raises(dataclasses.FrozenInstanceError):
            node.lifecycle = LifecycleMode.PERSISTENT  # type: ignore[misc]


# ============================================================
# 2. AgentCapabilities
# ============================================================


class TestAgentCapabilities:
    def test_max_depth_default_is_none(self) -> None:
        caps = AgentCapabilities()
        assert caps.max_depth is None

    def test_can_delegate_authority_default_is_false(self) -> None:
        caps = AgentCapabilities()
        assert caps.can_delegate_authority is False

    def test_custom_max_depth_and_delegate_authority(self) -> None:
        caps = AgentCapabilities(max_depth=3, can_delegate_authority=True)
        assert caps.max_depth == 3
        assert caps.can_delegate_authority is True

    def test_frozen_immutability(self) -> None:
        caps = AgentCapabilities()
        with pytest.raises(dataclasses.FrozenInstanceError):
            caps.max_depth = 10  # type: ignore[misc]


# ============================================================
# 3. GraphBuilder
# ============================================================


class TestGraphBuilder:
    async def test_add_root_with_lifecycle_and_hooks(self) -> None:
        store = InMemoryAgentGraph()
        builder = GraphBuilder(store)
        builder.add_root(
            "ceo", "CEO", "executive",
            lifecycle=LifecycleMode.PERSISTENT,
            hooks=("pre_check",),
        )
        snapshot = await builder.build()
        root = snapshot.nodes[0]
        assert root.lifecycle == LifecycleMode.PERSISTENT
        assert root.hooks == ("pre_check",)

    async def test_add_child_with_lifecycle_and_hooks(self) -> None:
        store = InMemoryAgentGraph()
        builder = GraphBuilder(store)
        builder.add_root("ceo", "CEO", "executive")
        builder.add_child(
            "eng", "ceo", "Eng", "engineer",
            lifecycle=LifecycleMode.EPHEMERAL,
            hooks=("hook_a", "hook_b"),
        )
        snapshot = await builder.build()
        child = [n for n in snapshot.nodes if n.id == "eng"][0]
        assert child.lifecycle == LifecycleMode.EPHEMERAL
        assert child.hooks == ("hook_a", "hook_b")

    async def test_from_dict_parses_lifecycle_hooks_capabilities(self) -> None:
        config = {
            "id": "ceo",
            "name": "CEO",
            "role": "executive",
            "lifecycle": "persistent",
            "hooks": ["audit_hook"],
            "capabilities": {
                "can_hire": True,
                "max_depth": 3,
                "can_delegate_authority": True,
            },
            "children": [
                {
                    "id": "dev",
                    "name": "Dev",
                    "role": "developer",
                    "lifecycle": "ephemeral",
                    "hooks": [],
                },
            ],
        }
        store = InMemoryAgentGraph()
        snapshot = await GraphBuilder.from_dict(config, store)

        ceo = [n for n in snapshot.nodes if n.id == "ceo"][0]
        assert ceo.lifecycle == LifecycleMode.PERSISTENT
        assert ceo.hooks == ("audit_hook",)
        assert ceo.capabilities.can_hire is True
        assert ceo.capabilities.max_depth == 3
        assert ceo.capabilities.can_delegate_authority is True

        dev = [n for n in snapshot.nodes if n.id == "dev"][0]
        assert dev.lifecycle == LifecycleMode.EPHEMERAL


# ============================================================
# 4. Governance
# ============================================================


class TestGovernanceCheckHireAllowed:
    async def test_per_agent_max_depth_enforcement(self) -> None:
        config = GraphGovernanceConfig(max_depth=10)
        store = InMemoryAgentGraph()
        root = AgentNode(
            id="root", name="Root", role="lead",
            capabilities=AgentCapabilities(can_hire=True, max_depth=1),
        )
        await store.add_node(root)
        result = await check_hire_allowed(config, root, store)
        assert result is not None
        assert "per-agent max_depth" in result


class TestGovernanceCheckAuthorityDelegation:
    def test_parent_without_can_hire_cannot_grant_can_hire_to_child(self) -> None:
        parent_caps = AgentCapabilities(can_hire=False)
        child_caps = AgentCapabilities(can_hire=True)
        result = check_authority_delegation(parent_caps, child_caps)
        assert result is not None
        assert "can_hire" in result

    def test_parent_without_delegate_authority_cannot_let_child_hire(self) -> None:
        parent_caps = AgentCapabilities(can_hire=True, can_delegate_authority=False)
        child_caps = AgentCapabilities(can_hire=True)
        result = check_authority_delegation(parent_caps, child_caps)
        assert result is not None
        assert "can_delegate_authority" in result

    def test_valid_authority_delegation_returns_none(self) -> None:
        parent_caps = AgentCapabilities(can_hire=True, can_delegate_authority=True)
        child_caps = AgentCapabilities(can_hire=True)
        result = check_authority_delegation(parent_caps, child_caps)
        assert result is None


class TestGovernanceValidateCapabilityDelegation:
    def test_tool_subset_enforcement(self) -> None:
        parent = AgentNode(
            id="p", name="P", role="lead",
            allowed_tools=("Read", "Write"),
        )
        result = validate_capability_delegation(
            parent,
            child_tools=("Read", "Bash"),
            child_skills=(),
            child_hooks=(),
        )
        assert result is not None
        assert "Bash" in result

    def test_empty_parent_tools_allows_all(self) -> None:
        parent = AgentNode(id="p", name="P", role="lead", allowed_tools=())
        result = validate_capability_delegation(
            parent,
            child_tools=("Read", "Write", "Bash"),
            child_skills=(),
            child_hooks=(),
        )
        assert result is None

    def test_extra_tools_returns_error(self) -> None:
        parent = AgentNode(
            id="p", name="P", role="lead",
            allowed_tools=("Read",),
        )
        result = validate_capability_delegation(
            parent,
            child_tools=("Read", "Edit", "Grep"),
            child_skills=(),
            child_hooks=(),
        )
        assert result is not None
        assert "Edit" in result or "Grep" in result


# ============================================================
# 5. HostAdapter Protocol — isinstance checks
# ============================================================


class TestHostAdapterProtocol:
    def test_agent_sdk_adapter_isinstance_host_adapter(self) -> None:
        adapter = AgentSDKAdapter()
        assert isinstance(adapter, HostAdapter)

    def test_codex_adapter_isinstance_host_adapter(self) -> None:
        adapter = CodexAdapter()
        assert isinstance(adapter, HostAdapter)

    def test_agent_handle_frozen(self) -> None:
        handle = AgentHandle(id="x", role="dev")
        with pytest.raises(dataclasses.FrozenInstanceError):
            handle.id = "y"  # type: ignore[misc]

    def test_agent_authority_frozen(self) -> None:
        auth = AgentAuthority(can_spawn=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            auth.can_spawn = False  # type: ignore[misc]


# ============================================================
# 6. AgentSDKAdapter
# ============================================================


class TestAgentSDKAdapter:
    @pytest.fixture()
    def adapter(self) -> AgentSDKAdapter:
        return AgentSDKAdapter()

    async def test_spawn_agent_returns_agent_handle(self, adapter: AgentSDKAdapter, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "cognitia.runtime.agent_sdk_adapter.AgentSDKAdapter.spawn_agent",
            self._patched_spawn,
        )
        handle = await adapter.spawn_agent("dev", "build feature")
        assert isinstance(handle, AgentHandle)
        assert handle.role == "dev"

    async def test_get_status_returns_idle_after_spawn(self, adapter: AgentSDKAdapter, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "cognitia.runtime.agent_sdk_adapter.AgentSDKAdapter.spawn_agent",
            self._patched_spawn,
        )
        handle = await adapter.spawn_agent("dev", "test")
        status = await adapter.get_status(handle)
        assert status == AgentHandleStatus.IDLE

    async def test_stop_agent_sets_stopped(self, adapter: AgentSDKAdapter, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "cognitia.runtime.agent_sdk_adapter.AgentSDKAdapter.spawn_agent",
            self._patched_spawn,
        )
        handle = await adapter.spawn_agent("dev", "test")
        await adapter.stop_agent(handle)
        status = await adapter.get_status(handle)
        assert status == AgentHandleStatus.STOPPED

    async def test_model_registry_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_registry()
        adapter = AgentSDKAdapter(default_model="opus")
        handle = await self._patched_spawn(adapter, "dev", "test")
        assert "model" in handle.metadata

    @staticmethod
    async def _patched_spawn(
        self_adapter: AgentSDKAdapter,
        role: str,
        goal: str,
        **kwargs: Any,
    ) -> AgentHandle:
        """Spawn without requiring claude_code_sdk import."""
        import uuid

        resolved_model = get_registry().resolve(kwargs.get("model") or self_adapter._default_model)
        agent_id = f"claude-{role}-{uuid.uuid4().hex[:8]}"
        lifecycle = kwargs.get("lifecycle", LifecycleMode.SUPERVISED)

        self_adapter._sessions[agent_id] = {
            "model": resolved_model,
            "system_prompt": kwargs.get("system_prompt", "") or f"You are a {role} agent. Goal: {goal}",
            "tools": kwargs.get("tools", ()),
            "goal": goal,
            "lifecycle": lifecycle,
        }
        self_adapter._statuses[agent_id] = AgentHandleStatus.IDLE

        return AgentHandle(
            id=agent_id,
            role=role,
            lifecycle=lifecycle,
            metadata={"model": resolved_model, "goal": goal},
        )


# ============================================================
# 7. CodexAdapter
# ============================================================


class TestCodexAdapter:
    @pytest.fixture()
    def adapter(self) -> CodexAdapter:
        return CodexAdapter()

    async def test_spawn_agent_returns_agent_handle(self, adapter: CodexAdapter) -> None:
        handle = await adapter.spawn_agent("dev", "build feature")
        assert isinstance(handle, AgentHandle)
        assert handle.role == "dev"
        assert handle.metadata.get("provider") == "openai"

    async def test_get_status_returns_idle_after_spawn(self, adapter: CodexAdapter) -> None:
        handle = await adapter.spawn_agent("dev", "test")
        status = await adapter.get_status(handle)
        assert status == AgentHandleStatus.IDLE

    async def test_stop_agent_sets_stopped(self, adapter: CodexAdapter) -> None:
        handle = await adapter.spawn_agent("dev", "test")
        await adapter.stop_agent(handle)
        status = await adapter.get_status(handle)
        assert status == AgentHandleStatus.STOPPED


# ============================================================
# 8. GoalQueue
# ============================================================


class TestGoalQueue:
    @pytest.fixture()
    def queue(self) -> GoalQueue:
        return GoalQueue()

    def test_submit_dequeue_complete_flow(self, queue: GoalQueue) -> None:
        entry = queue.submit("Build API")
        assert entry.status == GoalStatus.QUEUED

        dequeued = queue.dequeue()
        assert dequeued is not None
        assert dequeued.id == entry.id
        assert dequeued.status == GoalStatus.RUNNING

        queue.mark_complete(entry.id, run_id="run-1")
        all_goals = queue.list_all()
        assert all_goals[0].status == GoalStatus.COMPLETED
        assert all_goals[0].run_id == "run-1"

    def test_fifo_ordering(self, queue: GoalQueue) -> None:
        e1 = queue.submit("First")
        e2 = queue.submit("Second")
        e3 = queue.submit("Third")

        d1 = queue.dequeue()
        d2 = queue.dequeue()
        d3 = queue.dequeue()

        assert d1 is not None and d1.id == e1.id
        assert d2 is not None and d2.id == e2.id
        assert d3 is not None and d3.id == e3.id

    def test_mark_failed(self, queue: GoalQueue) -> None:
        entry = queue.submit("Risky task")
        queue.dequeue()
        queue.mark_failed(entry.id)
        goals = queue.list_all()
        assert goals[0].status == GoalStatus.FAILED

    def test_list_all_and_list_pending(self, queue: GoalQueue) -> None:
        queue.submit("A")
        queue.submit("B")
        queue.dequeue()  # A becomes RUNNING

        assert len(queue.list_all()) == 2
        pending = queue.list_pending()
        assert len(pending) == 1
        assert pending[0].goal == "B"

    def test_size_counts_queued_only(self, queue: GoalQueue) -> None:
        queue.submit("A")
        queue.submit("B")
        assert queue.size == 2

        queue.dequeue()
        assert queue.size == 1

    def test_peek_does_not_remove(self, queue: GoalQueue) -> None:
        queue.submit("Peeked")
        peeked = queue.peek()
        assert peeked is not None
        assert peeked.goal == "Peeked"
        assert queue.size == 1  # still there

    def test_dequeue_empty_returns_none(self, queue: GoalQueue) -> None:
        assert queue.dequeue() is None

    def test_mark_complete_unknown_raises(self, queue: GoalQueue) -> None:
        with pytest.raises(KeyError):
            queue.mark_complete("nonexistent")


# ============================================================
# 9. ModelRegistry — codex resolution
# ============================================================


class TestModelRegistryCodex:
    @pytest.fixture(autouse=True)
    def _reset(self) -> None:
        reset_registry()

    def test_resolve_codex_to_codex_mini(self) -> None:
        registry = get_registry()
        resolved = registry.resolve("codex")
        assert resolved == "codex-mini"

    def test_get_provider_codex_mini_is_openai(self) -> None:
        registry = get_registry()
        provider = registry.get_provider("codex-mini")
        assert provider == "openai"


# ============================================================
# 10. Orchestrator lifecycle
# ============================================================


class TestOrchestratorLifecycle:
    @pytest.fixture()
    def store(self) -> InMemoryAgentGraph:
        return InMemoryAgentGraph()

    @pytest.fixture()
    def event_bus(self) -> _SimpleEventBus:
        return _SimpleEventBus()

    async def test_ephemeral_agent_removed_after_task(self, store: InMemoryAgentGraph, event_bus: _SimpleEventBus) -> None:
        from cognitia.multi_agent.graph_orchestrator import DefaultGraphOrchestrator

        root = AgentNode(
            id="root", name="Root", role="lead",
            lifecycle=LifecycleMode.SUPERVISED,
            capabilities=AgentCapabilities(can_hire=True, can_delegate=True),
        )
        ephemeral = AgentNode(
            id="worker", name="Worker", role="dev",
            parent_id="root",
            lifecycle=LifecycleMode.EPHEMERAL,
        )
        await store.add_node(root)
        await store.add_node(ephemeral)

        runner = AsyncMock(return_value="done")
        task_board = _MinimalTaskBoard()
        orch = DefaultGraphOrchestrator(
            store, task_board, runner, event_bus=event_bus,
        )

        # Directly test lifecycle handler
        await orch._handle_lifecycle("worker", "task-1")

        node_after = await store.get_node("worker")
        assert node_after is None, "Ephemeral agent should be removed"

        topics = [e[0] for e in event_bus.events]
        assert "graph.agent.self_terminated" in topics

    async def test_supervised_agent_stays_after_task(self, store: InMemoryAgentGraph, event_bus: _SimpleEventBus) -> None:
        from cognitia.multi_agent.graph_orchestrator import DefaultGraphOrchestrator

        root = AgentNode(
            id="root", name="Root", role="lead",
            lifecycle=LifecycleMode.SUPERVISED,
        )
        await store.add_node(root)

        runner = AsyncMock(return_value="done")
        task_board = _MinimalTaskBoard()
        orch = DefaultGraphOrchestrator(
            store, task_board, runner, event_bus=event_bus,
        )

        await orch._handle_lifecycle("root", "task-2")

        node_after = await store.get_node("root")
        assert node_after is not None, "Supervised agent should stay"

        topics = [e[0] for e in event_bus.events]
        assert "graph.agent.awaiting_review" in topics

    async def test_persistent_agent_resets_to_idle(self, store: InMemoryAgentGraph, event_bus: _SimpleEventBus) -> None:
        from cognitia.multi_agent.graph_orchestrator import DefaultGraphOrchestrator
        from cognitia.multi_agent.registry_types import AgentStatus

        persistent = AgentNode(
            id="svc", name="Service", role="service",
            lifecycle=LifecycleMode.PERSISTENT,
            status=AgentStatus.RUNNING,
        )
        await store.add_node(persistent)

        runner = AsyncMock(return_value="done")
        task_board = _MinimalTaskBoard()
        orch = DefaultGraphOrchestrator(
            store, task_board, runner, event_bus=event_bus,
        )

        await orch._handle_lifecycle("svc", "task-3")

        topics = [e[0] for e in event_bus.events]
        assert "graph.agent.ready" in topics


# ============================================================
# Test helpers
# ============================================================


class _SimpleEventBus:
    """Minimal event bus for lifecycle tests."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, topic: str, data: dict[str, Any]) -> None:
        self.events.append((topic, data))


class _MinimalTaskBoard:
    """Minimal stub for task board (not exercised in lifecycle tests)."""

    async def create_task(self, *args: Any, **kwargs: Any) -> Any:
        return None

    async def checkout_task(self, *args: Any, **kwargs: Any) -> Any:
        return None

    async def complete_task(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def cancel_task(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def get_task(self, *args: Any, **kwargs: Any) -> Any:
        return None
