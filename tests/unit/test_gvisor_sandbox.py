"""Tests for NetworkPolicy and GVisorSandboxProvider. TDD.

Covers:
  - NetworkPolicy.to_iptables_rules(): allow egress, drop egress, default drop,
    ordering (allow before default-drop), allow-without-port, empty-policy
  - GVisorSandboxProvider: satisfies SandboxProvider protocol, constructs correct
    runsc exec command, exposes network policy rules, honours denied_commands,
    delegates execute/read_file/list_dir/glob_files to injectable command runner,
    blocks path traversal in glob_files
"""

from __future__ import annotations

import pytest
from swarmline.tools.types import SandboxConfig


@pytest.fixture()
def sandbox_config() -> SandboxConfig:
    return SandboxConfig(
        root_path="/tmp",
        user_id="u1",
        topic_id="t1",
        timeout_seconds=5,
        denied_commands=frozenset({"rm"}),
    )


# ---------------------------------------------------------------------------
# NetworkPolicy
# ---------------------------------------------------------------------------


class TestNetworkPolicy:
    def test_allow_tcp_egress_with_port_emits_correct_rule(self) -> None:
        # Arrange
        from swarmline.tools.network_policy import (
            EgressAction,
            EgressRule,
            NetworkPolicy,
        )

        policy = NetworkPolicy(
            egress_rules=[
                EgressRule(
                    action=EgressAction.ALLOW,
                    destination="10.0.0.0/8",
                    protocol="tcp",
                    port=443,
                )
            ],
            default_drop=False,
        )

        # Act
        rules = policy.to_iptables_rules()

        # Assert
        assert "iptables -A OUTPUT -d 10.0.0.0/8 -p tcp --dport 443 -j ACCEPT" in rules

    def test_drop_egress_rule_emits_correct_rule(self) -> None:
        # Arrange
        from swarmline.tools.network_policy import (
            EgressAction,
            EgressRule,
            NetworkPolicy,
        )

        policy = NetworkPolicy(
            egress_rules=[
                EgressRule(action=EgressAction.DROP, destination="192.168.0.0/16")
            ],
            default_drop=False,
        )

        # Act
        rules = policy.to_iptables_rules()

        # Assert
        assert "iptables -A OUTPUT -d 192.168.0.0/16 -j DROP" in rules

    def test_default_drop_appended_as_last_rule_when_enabled(self) -> None:
        # Arrange
        from swarmline.tools.network_policy import NetworkPolicy

        policy = NetworkPolicy(egress_rules=[], default_drop=True)

        # Act
        rules = policy.to_iptables_rules()

        # Assert
        assert rules[-1] == "iptables -A OUTPUT -j DROP"

    def test_allow_rule_precedes_default_drop_in_output(self) -> None:
        # Arrange
        from swarmline.tools.network_policy import (
            EgressAction,
            EgressRule,
            NetworkPolicy,
        )

        policy = NetworkPolicy(
            egress_rules=[
                EgressRule(
                    action=EgressAction.ALLOW,
                    destination="8.8.8.8",
                    protocol="udp",
                    port=53,
                )
            ],
            default_drop=True,
        )

        # Act
        rules = policy.to_iptables_rules()

        # Assert — ACCEPT rule first, default DROP last
        assert len(rules) == 2
        assert "ACCEPT" in rules[0]
        assert rules[-1] == "iptables -A OUTPUT -j DROP"

    def test_allow_rule_without_port_omits_dport_flag(self) -> None:
        # Arrange
        from swarmline.tools.network_policy import (
            EgressAction,
            EgressRule,
            NetworkPolicy,
        )

        policy = NetworkPolicy(
            egress_rules=[
                EgressRule(
                    action=EgressAction.ALLOW,
                    destination="0.0.0.0/0",
                    protocol="tcp",
                )
            ],
            default_drop=False,
        )

        # Act
        rules = policy.to_iptables_rules()

        # Assert
        assert rules == ["iptables -A OUTPUT -d 0.0.0.0/0 -p tcp -j ACCEPT"]

    def test_empty_policy_with_default_drop_emits_single_rule(self) -> None:
        # Arrange
        from swarmline.tools.network_policy import NetworkPolicy

        policy = NetworkPolicy(egress_rules=[], default_drop=True)

        # Act
        rules = policy.to_iptables_rules()

        # Assert
        assert rules == ["iptables -A OUTPUT -j DROP"]

    def test_empty_policy_without_default_drop_emits_no_rules(self) -> None:
        # Arrange
        from swarmline.tools.network_policy import NetworkPolicy

        policy = NetworkPolicy(egress_rules=[], default_drop=False)

        # Act + Assert
        assert policy.to_iptables_rules() == []


# ---------------------------------------------------------------------------
# GVisorSandboxProvider
# ---------------------------------------------------------------------------


class TestGVisorSandboxProvider:
    async def test_satisfies_sandbox_provider_protocol(self, sandbox_config) -> None:
        # Arrange
        from swarmline.tools.protocols import SandboxProvider
        from swarmline.tools.sandbox_gvisor import GVisorConfig, GVisorSandboxProvider

        gconfig = GVisorConfig(container_id="test-container")
        provider = GVisorSandboxProvider(sandbox_config, gconfig)

        # Assert
        assert isinstance(provider, SandboxProvider)

    async def test_build_runsc_exec_includes_binary_exec_and_container(
        self, sandbox_config
    ) -> None:
        # Arrange
        from swarmline.tools.sandbox_gvisor import GVisorConfig, GVisorSandboxProvider

        gconfig = GVisorConfig(
            runsc_binary="/usr/local/bin/runsc",
            container_id="test-container",
            platform="systrap",
            network="sandbox",
        )
        provider = GVisorSandboxProvider(sandbox_config, gconfig)

        # Act
        cmd = provider.build_runsc_exec(["echo", "hello"])

        # Assert — structure: runsc ... exec <container_id> echo hello
        assert cmd[0] == "/usr/local/bin/runsc"
        assert "exec" in cmd
        idx_exec = cmd.index("exec")
        assert cmd[idx_exec + 1] == "test-container"
        assert cmd[-2:] == ["echo", "hello"]

    async def test_network_policy_rules_accessible_via_provider(
        self, sandbox_config
    ) -> None:
        # Arrange
        from swarmline.tools.network_policy import (
            EgressAction,
            EgressRule,
            NetworkPolicy,
        )
        from swarmline.tools.sandbox_gvisor import GVisorConfig, GVisorSandboxProvider

        policy = NetworkPolicy(
            egress_rules=[
                EgressRule(
                    action=EgressAction.ALLOW,
                    destination="8.8.8.8",
                    protocol="udp",
                    port=53,
                ),
            ],
            default_drop=True,
        )
        gconfig = GVisorConfig(container_id="test-container")
        provider = GVisorSandboxProvider(sandbox_config, gconfig, network_policy=policy)

        # Act
        rules = provider.get_network_policy_rules()

        # Assert
        assert len(rules) == 2
        assert "8.8.8.8" in rules[0]
        assert "ACCEPT" in rules[0]
        assert rules[-1] == "iptables -A OUTPUT -j DROP"

    async def test_no_network_policy_returns_empty_list(self, sandbox_config) -> None:
        # Arrange
        from swarmline.tools.sandbox_gvisor import GVisorConfig, GVisorSandboxProvider

        gconfig = GVisorConfig(container_id="test-container")
        provider = GVisorSandboxProvider(sandbox_config, gconfig, network_policy=None)

        # Act + Assert
        assert provider.get_network_policy_rules() == []

    async def test_execute_honors_denied_commands(self, sandbox_config) -> None:
        # Arrange
        from swarmline.tools.sandbox_gvisor import GVisorConfig, GVisorSandboxProvider
        from swarmline.tools.types import SandboxViolation

        gconfig = GVisorConfig(container_id="test-container")
        provider = GVisorSandboxProvider(sandbox_config, gconfig)

        # Act + Assert — "rm" is in denied_commands of sandbox_config
        with pytest.raises(SandboxViolation):
            await provider.execute("rm -rf /")

    async def test_execute_delegates_to_command_runner_via_runsc_exec(
        self, sandbox_config
    ) -> None:
        # Arrange
        from swarmline.tools.sandbox_gvisor import GVisorConfig, GVisorSandboxProvider
        from swarmline.tools.types import ExecutionResult

        captured: list[list[str]] = []

        async def fake_runner(cmd: list[str]) -> ExecutionResult:
            captured.append(cmd)
            return ExecutionResult(
                stdout="output\n", stderr="", exit_code=0, timed_out=False
            )

        gconfig = GVisorConfig(container_id="test-container")
        provider = GVisorSandboxProvider(
            sandbox_config, gconfig, _command_runner=fake_runner
        )

        # Act
        result = await provider.execute("echo hello")

        # Assert — command runner called with runsc exec ... echo hello
        assert len(captured) == 1
        assert "runsc" in captured[0][0]
        assert "exec" in captured[0]
        assert result.stdout == "output\n"
        assert result.exit_code == 0

    async def test_read_file_delegates_to_command_runner(self, sandbox_config) -> None:
        # Arrange
        from swarmline.tools.sandbox_gvisor import GVisorConfig, GVisorSandboxProvider
        from swarmline.tools.types import ExecutionResult

        async def fake_runner(cmd: list[str]) -> ExecutionResult:
            return ExecutionResult(
                stdout="file content\n", stderr="", exit_code=0, timed_out=False
            )

        gconfig = GVisorConfig(container_id="test-container")
        provider = GVisorSandboxProvider(
            sandbox_config, gconfig, _command_runner=fake_runner
        )

        # Act
        content = await provider.read_file("test.txt")

        # Assert
        assert content == "file content\n"

    async def test_write_file_delegates_to_command_runner(self, sandbox_config) -> None:
        # Arrange
        from swarmline.tools.sandbox_gvisor import GVisorConfig, GVisorSandboxProvider
        from swarmline.tools.types import ExecutionResult

        captured: list[list[str]] = []

        async def fake_runner(cmd: list[str]) -> ExecutionResult:
            captured.append(cmd)
            return ExecutionResult(stdout="", stderr="", exit_code=0, timed_out=False)

        gconfig = GVisorConfig(container_id="test-container")
        provider = GVisorSandboxProvider(
            sandbox_config, gconfig, _command_runner=fake_runner
        )

        # Act
        await provider.write_file("test.txt", "hello world")

        # Assert — runner was called at least once
        assert len(captured) >= 1

    async def test_list_dir_parses_newline_separated_output(
        self, sandbox_config
    ) -> None:
        # Arrange
        from swarmline.tools.sandbox_gvisor import GVisorConfig, GVisorSandboxProvider
        from swarmline.tools.types import ExecutionResult

        async def fake_runner(cmd: list[str]) -> ExecutionResult:
            return ExecutionResult(
                stdout="a.txt\nb.py\n", stderr="", exit_code=0, timed_out=False
            )

        gconfig = GVisorConfig(container_id="test-container")
        provider = GVisorSandboxProvider(
            sandbox_config, gconfig, _command_runner=fake_runner
        )

        # Act
        entries = await provider.list_dir(".")

        # Assert
        assert sorted(entries) == ["a.txt", "b.py"]

    async def test_glob_files_path_traversal_blocked(self, sandbox_config) -> None:
        # Arrange
        from swarmline.tools.sandbox_gvisor import GVisorConfig, GVisorSandboxProvider
        from swarmline.tools.types import SandboxViolation

        gconfig = GVisorConfig(container_id="test-container")
        provider = GVisorSandboxProvider(sandbox_config, gconfig)

        # Act + Assert
        with pytest.raises(SandboxViolation):
            await provider.glob_files("../../*.py")

    async def test_glob_files_delegates_to_command_runner(self, sandbox_config) -> None:
        # Arrange
        from swarmline.tools.sandbox_gvisor import GVisorConfig, GVisorSandboxProvider
        from swarmline.tools.types import ExecutionResult

        async def fake_runner(cmd: list[str]) -> ExecutionResult:
            return ExecutionResult(
                stdout="main.py\nsrc/utils.py\n",
                stderr="",
                exit_code=0,
                timed_out=False,
            )

        gconfig = GVisorConfig(container_id="test-container")
        provider = GVisorSandboxProvider(
            sandbox_config, gconfig, _command_runner=fake_runner
        )

        # Act
        files = await provider.glob_files("**/*.py")

        # Assert
        assert "main.py" in files
        assert "src/utils.py" in files
