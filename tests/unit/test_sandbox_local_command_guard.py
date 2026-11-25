"""Unit: LocalSandboxProvider optional command-risk guard (REQ-OSS-001/002).

The guard is OPT-IN. When no ``command_risk_policy`` is supplied (the default
constructor) the exec path is byte-identical to before — classification is never
invoked. When a policy is supplied, the command is classified + gated before any
subprocess is spawned.

TDD: written BEFORE the guard is wired into sandbox_local.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from swarmline.command_safety import AccessDecision, CommandRiskPolicy, RiskLevel
from swarmline.tools.sandbox_local import LocalSandboxProvider
from swarmline.tools.types import SandboxConfig, SandboxViolation


@pytest.fixture()
def config(tmp_path: object) -> SandboxConfig:
    """Sandbox config that allows host execution and denies nothing.

    ``denied_commands`` is empty so that the command-risk guard — not the
    denylist — is the only thing that can block a command.
    """
    return SandboxConfig(
        root_path=str(tmp_path),
        user_id="user-1",
        topic_id="topic-1",
        timeout_seconds=5,
        allow_host_execution=True,
    )


class _SpyPolicy:
    """A CommandGuard that records classify() calls and delegates to the real policy."""

    def __init__(self) -> None:
        self.classify_calls: list[str] = []
        self._delegate = CommandRiskPolicy()

    def classify(self, cmd: str) -> tuple[RiskLevel, str]:
        self.classify_calls.append(cmd)
        return self._delegate.classify(cmd)

    def decide(self, level: RiskLevel, *, interactive: bool) -> AccessDecision:
        return self._delegate.decide(level, interactive=interactive)


# ---------------------------------------------------------------------------
# Guard ABSENT (default) → byte-identical, no classification
# ---------------------------------------------------------------------------


async def test_default_constructor_does_not_classify(config: SandboxConfig) -> None:
    """REQ-OSS-002: with no guard, execute() never invokes the classifier."""
    with patch.object(CommandRiskPolicy, "classify") as spy:
        provider = LocalSandboxProvider(config)
        result = await provider.execute("echo hello")
    spy.assert_not_called()
    assert result.stdout == "hello\n"
    assert result.exit_code == 0


async def test_default_constructor_does_not_gate_risky_command(
    config: SandboxConfig,
) -> None:
    """REQ-OSS-002: a command the guard WOULD gate runs unblocked when no guard is set.

    ``git push --force`` classifies as APPROVAL_REQUIRED, but with no guard the
    sandbox just runs it (it fails harmlessly in a non-repo workspace) — proving
    the default path performs no gating.
    """
    provider = LocalSandboxProvider(config)  # no command_risk_policy
    result = await provider.execute("git push --force")
    # No SandboxViolation raised; subprocess ran and returned a result object.
    assert isinstance(result.exit_code, int)


# ---------------------------------------------------------------------------
# Guard PRESENT → classifies + gates
# ---------------------------------------------------------------------------


async def test_guard_classifies_when_present(config: SandboxConfig) -> None:
    """The guard invokes classify() exactly once for the command under evaluation."""
    spy = _SpyPolicy()
    provider = LocalSandboxProvider(config, command_risk_policy=spy)
    with pytest.raises(SandboxViolation):
        await provider.execute("git push --force")
    assert spy.classify_calls == ["git push --force"]


async def test_guard_allows_safe_command(config: SandboxConfig) -> None:
    """A SAFE command is allowed and executes normally when the guard is present."""
    provider = LocalSandboxProvider(config, command_risk_policy=CommandRiskPolicy())
    result = await provider.execute("echo ok")
    assert result.stdout == "ok\n"
    assert result.exit_code == 0


async def test_guard_blocks_approval_required_in_non_interactive(
    config: SandboxConfig,
) -> None:
    """REQ-OSS-001: APPROVAL_REQUIRED → DENY in the non-interactive sandbox path."""
    provider = LocalSandboxProvider(config, command_risk_policy=CommandRiskPolicy())
    with pytest.raises(SandboxViolation):
        await provider.execute("git push --force")


async def test_guard_blocks_hardline_before_subprocess(config: SandboxConfig) -> None:
    """REQ-OSS-001: HARDLINE is blocked BEFORE any subprocess is spawned.

    create_subprocess_exec is patched to fail the test if reached — a destructive
    hardline command must never actually run.
    """

    async def _fail_if_called(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("subprocess must not be spawned for a HARDLINE command")

    provider = LocalSandboxProvider(config, command_risk_policy=CommandRiskPolicy())
    with patch("asyncio.create_subprocess_exec", _fail_if_called):
        with pytest.raises(SandboxViolation):
            await provider.execute("rm -rf /")
