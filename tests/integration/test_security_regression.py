"""Security regression tests - by P0 from audita. Verify: prefix-bypass path isolation, cross-tenant isolation,
memory bank path traversal.
"""

from __future__ import annotations

from datetime import UTC

import pytest
from cognitia.memory_bank.types import MemoryBankConfig, MemoryBankViolation
from cognitia.tools.types import SandboxConfig, SandboxViolation

pytestmark = pytest.mark.security


class TestPathIsolationPrefixBypass:
    """P0: prefix-bypass cherez startswith -> is_relative_to."""

    async def test_sandbox_workspace_prefix_bypass(self, tmp_path) -> None:
        """workspace=/tmp/ws -> popytka chitat /tmp/ws2 cherez 'ws2/secret'."""
        from cognitia.tools.sandbox_local import LocalSandboxProvider

        # Create dva workspace: ws and ws2
        ws = tmp_path / "u1" / "t1" / "workspace"
        ws.mkdir(parents=True)
        ws2 = tmp_path / "u1" / "t1" / "workspace2"
        ws2.mkdir(parents=True)
        secret = ws2 / "secret.txt"
        secret.write_text("SECRET")

        sandbox = LocalSandboxProvider(
            SandboxConfig(root_path=str(tmp_path), user_id="u1", topic_id="t1")
        )

        # Popytka prochitat file from workspace2 cherez otnositelnyy put
        with pytest.raises((SandboxViolation, FileNotFoundError)):
            await sandbox.read_file("../workspace2/secret.txt")

    async def test_memory_bank_prefix_bypass(self, tmp_path) -> None:
        """memory=/tmp/u1/t1/memory -> popytka chitat /tmp/u1/t1/memory2/secret."""
        from cognitia.memory_bank.fs_provider import FilesystemMemoryBankProvider

        cfg = MemoryBankConfig(enabled=True, root_path=tmp_path)
        p = FilesystemMemoryBankProvider(cfg, user_id="u1", topic_id="t1")

        # Create «chuzhuyu» directory ryadom
        evil_dir = tmp_path / "u1" / "t1" / "memory2"
        evil_dir.mkdir(parents=True)
        (evil_dir / "secret.md").write_text("SECRET")

        with pytest.raises(MemoryBankViolation):
            await p.read_file("../memory2/secret.md")


class TestCrossTenantIsolation:
    """Security: cross-user and cross-topic isolation."""

    async def test_sandbox_cross_user_cannot_read(self, tmp_path) -> None:
        from cognitia.tools.sandbox_local import LocalSandboxProvider

        sb_a = LocalSandboxProvider(
            SandboxConfig(root_path=str(tmp_path), user_id="alice", topic_id="t1")
        )
        sb_b = LocalSandboxProvider(
            SandboxConfig(root_path=str(tmp_path), user_id="bob", topic_id="t1")
        )

        await sb_a.write_file("private.txt", "alice-secret")

        with pytest.raises(FileNotFoundError):
            await sb_b.read_file("private.txt")

    async def test_memory_bank_cross_user_cannot_read(self, tmp_path) -> None:
        from cognitia.memory_bank.fs_provider import FilesystemMemoryBankProvider

        cfg = MemoryBankConfig(enabled=True, root_path=tmp_path)
        pa = FilesystemMemoryBankProvider(cfg, user_id="alice", topic_id="t1")
        pb = FilesystemMemoryBankProvider(cfg, user_id="bob", topic_id="t1")

        await pa.write_file("MEMORY.md", "alice-knowledge")
        assert await pb.read_file("MEMORY.md") is None

    async def test_plan_store_multi_tenant(self) -> None:
        """PlanStore filtruet list_plans by user_id/topic_id."""
        from datetime import datetime

        from cognitia.orchestration.plan_store import InMemoryPlanStore
        from cognitia.orchestration.types import Plan, PlanStep

        store = InMemoryPlanStore()
        now = datetime.now(tz=UTC)

        store.set_namespace("alice", "t1")
        await store.save(
            Plan(
                id="p1",
                goal="alice-plan",
                steps=[PlanStep(id="s1", description="x")],
                created_at=now,
            )
        )

        store.set_namespace("bob", "t1")
        await store.save(
            Plan(
                id="p2", goal="bob-plan", steps=[PlanStep(id="s1", description="y")], created_at=now
            )
        )

        alice_plans = await store.list_plans("alice", "t1")
        bob_plans = await store.list_plans("bob", "t1")

        assert len(alice_plans) == 1
        assert alice_plans[0].goal == "alice-plan"
        assert len(bob_plans) == 1
        assert bob_plans[0].goal == "bob-plan"


class TestPolicyCaseSensitivity:
    """P1: ToolPolicy obrabatyvaet oba naming convention."""

    def test_snake_case_denied(self) -> None:
        from cognitia.policy import DefaultToolPolicy, PermissionDeny
        from cognitia.policy.tool_policy import ToolPolicyInput

        policy = DefaultToolPolicy()
        state = ToolPolicyInput(
            tool_name="", input_data={}, active_skill_ids=[], allowed_local_tools=set()
        )
        # snake_case should byt zapreshchen
        assert isinstance(policy.can_use_tool("bash", {}, state), PermissionDeny)
        assert isinstance(policy.can_use_tool("read", {}, state), PermissionDeny)

    def test_pascal_case_denied(self) -> None:
        from cognitia.policy import DefaultToolPolicy, PermissionDeny
        from cognitia.policy.tool_policy import ToolPolicyInput

        policy = DefaultToolPolicy()
        state = ToolPolicyInput(
            tool_name="", input_data={}, active_skill_ids=[], allowed_local_tools=set()
        )
        assert isinstance(policy.can_use_tool("Bash", {}, state), PermissionDeny)
        assert isinstance(policy.can_use_tool("Read", {}, state), PermissionDeny)

    def test_whitelist_both_cases(self) -> None:
        from cognitia.policy import DefaultToolPolicy, PermissionAllow
        from cognitia.policy.tool_policy import ToolPolicyInput

        policy = DefaultToolPolicy(allowed_system_tools={"Bash", "bash"})
        state = ToolPolicyInput(
            tool_name="", input_data={}, active_skill_ids=[], allowed_local_tools={"Bash", "bash"}
        )
        assert isinstance(policy.can_use_tool("Bash", {}, state), PermissionAllow)
        assert isinstance(policy.can_use_tool("bash", {}, state), PermissionAllow)
