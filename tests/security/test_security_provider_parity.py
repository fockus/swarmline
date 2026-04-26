"""Security suite: path isolation, tenant boundaries, policy parity."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from swarmline.policy import DefaultToolPolicy, PermissionAllow, PermissionDeny
from swarmline.policy.tool_policy import ToolPolicyInput
from swarmline.todo.inmemory_provider import InMemoryTodoProvider
from swarmline.todo.types import TodoItem
from swarmline.tools.sandbox_docker import DockerSandboxProvider
from swarmline.tools.sandbox_e2b import E2BSandboxProvider
from swarmline.tools.sandbox_local import LocalSandboxProvider
from swarmline.tools.sandbox_openshell import OpenShellSandboxProvider
from swarmline.tools.types import SandboxConfig, SandboxViolation

pytestmark = pytest.mark.security


def _sandbox_config(
    tmp_path, user_id: str = "u1", topic_id: str = "t1"
) -> SandboxConfig:
    return SandboxConfig(
        root_path=str(tmp_path),
        user_id=user_id,
        topic_id=topic_id,
        denied_commands=frozenset({"rm", "sudo"}),
        timeout_seconds=1,
    )


class TestPathIsolationParity:
    async def test_traversal_blocked_for_all_sandbox_providers(self, tmp_path) -> None:
        local = LocalSandboxProvider(_sandbox_config(tmp_path))
        e2b = E2BSandboxProvider(_sandbox_config(tmp_path), _sandbox=AsyncMock())
        docker = DockerSandboxProvider(
            _sandbox_config(tmp_path), _container=AsyncMock()
        )
        openshell = OpenShellSandboxProvider(
            _sandbox_config(tmp_path), _session=AsyncMock()
        )

        with pytest.raises(SandboxViolation):
            await local.read_file("../secret.txt")
        with pytest.raises(SandboxViolation):
            await e2b.read_file("../secret.txt")
        with pytest.raises(SandboxViolation):
            await docker.read_file("../secret.txt")
        with pytest.raises(SandboxViolation):
            await openshell.read_file("../secret.txt")

    async def test_denied_commands_blocked_before_execution(self, tmp_path) -> None:
        mock_e2b = AsyncMock()
        mock_docker = AsyncMock()
        mock_openshell = AsyncMock()

        e2b = E2BSandboxProvider(_sandbox_config(tmp_path), _sandbox=mock_e2b)
        docker = DockerSandboxProvider(
            _sandbox_config(tmp_path), _container=mock_docker
        )
        openshell = OpenShellSandboxProvider(
            _sandbox_config(tmp_path), _session=mock_openshell
        )

        with pytest.raises(SandboxViolation):
            await e2b.execute("rm -rf /workspace")
        with pytest.raises(SandboxViolation):
            await docker.execute("rm -rf /workspace")
        with pytest.raises(SandboxViolation):
            await openshell.execute("rm -rf /workspace")

        mock_e2b.process.start.assert_not_called()
        mock_docker.exec_run.assert_not_called()
        mock_openshell.exec.assert_not_called()


class TestTenantBoundaries:
    async def test_todo_provider_isolated_by_user_topic(self) -> None:
        alice = InMemoryTodoProvider(user_id="alice", topic_id="t1")
        bob = InMemoryTodoProvider(user_id="bob", topic_id="t1")

        now = datetime.now(tz=UTC)
        await alice.write_todos(
            [
                TodoItem(
                    id="a-1",
                    content="private-alice-task",
                    status="pending",
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        alice_todos = await alice.read_todos()
        bob_todos = await bob.read_todos()
        assert len(alice_todos) == 1
        assert alice_todos[0].content == "private-alice-task"
        assert bob_todos == []


class TestPolicyCaseParity:
    def test_policy_denies_and_allows_both_casing(self) -> None:
        policy = DefaultToolPolicy(allowed_system_tools={"Bash", "bash"})
        state = ToolPolicyInput(
            tool_name="",
            input_data={},
            active_skill_ids=[],
            allowed_local_tools={"Bash", "bash"},
        )

        assert isinstance(policy.can_use_tool("Bash", {}, state), PermissionAllow)
        assert isinstance(policy.can_use_tool("bash", {}, state), PermissionAllow)

        strict = DefaultToolPolicy()
        strict_state = ToolPolicyInput(
            tool_name="",
            input_data={},
            active_skill_ids=[],
            allowed_local_tools=set(),
        )
        assert isinstance(strict.can_use_tool("Bash", {}, strict_state), PermissionDeny)
        assert isinstance(strict.can_use_tool("bash", {}, strict_state), PermissionDeny)
